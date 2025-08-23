package services

// Downloads GitHub tarball (by branch) with ETag and swaps /data/content/<branch> atomically.
// Extracts only README.md and docs/**.

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type Config struct {
	Owner        string
	Repo         string
	Branch       string
	Token        string
	PollInterval time.Duration
	DataDir      string // /data/content/<branch>
}

type Updater struct {
	cfg      Config
	client   *http.Client
	etagFile string
}

func NewUpdater(cfg Config) *Updater {
	return &Updater{
		cfg:      cfg,
		client:   &http.Client{Timeout: 60 * time.Second},
		etagFile: filepath.Join(cfg.DataDir, ".etag"),
	}
}

func (u *Updater) Start(ctx context.Context, onSwap func(activeDir string) error) error {
	_ = os.MkdirAll(u.cfg.DataDir, 0o755)

	_ = u.trySync(onSwap) // initial best-effort
	t := time.NewTicker(u.cfg.PollInterval)
	defer t.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-t.C:
			_ = u.trySync(onSwap)
		}
	}
}

func (u *Updater) trySync(onSwap func(activeDir string) error) error {
	url := fmt.Sprintf("https://api.github.com/repos/%s/%s/tarball/%s", u.cfg.Owner, u.cfg.Repo, u.cfg.Branch)

	// HEAD: check ETag
	req, _ := http.NewRequest("HEAD", url, nil)
	if tok := strings.TrimSpace(u.cfg.Token); tok != "" {
		req.Header.Set("Authorization", "Bearer "+tok)
	}
	if etag, _ := os.ReadFile(u.etagFile); len(etag) > 0 {
		req.Header.Set("If-None-Match", string(etag))
	}
	res, err := u.client.Do(req)
	if err != nil {
		return err
	}
	res.Body.Close()

	if res.StatusCode == http.StatusNotModified {
		return nil
	}
	if res.StatusCode != http.StatusOK {
		return fmt.Errorf("HEAD tarball: %d", res.StatusCode)
	}

	newETag := res.Header.Get("ETag")

	// GET tarball
	getReq, _ := http.NewRequest("GET", url, nil)
	if tok := strings.TrimSpace(u.cfg.Token); tok != "" {
		getReq.Header.Set("Authorization", "Bearer "+tok)
	}
	if newETag != "" {
		getReq.Header.Set("If-None-Match", newETag)
	}
	getRes, err := u.client.Do(getReq)
	if err != nil {
		return err
	}
	defer getRes.Body.Close()

	if getRes.StatusCode == http.StatusNotModified {
		return nil
	}
	if getRes.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(getRes.Body)
		return fmt.Errorf("GET tarball: %d %s", getRes.StatusCode, string(b))
	}

	// Extract to tmp
	tmpRoot, err := os.MkdirTemp("", "docs-extract-*")
	if err != nil {
		return err
	}
	defer os.RemoveAll(tmpRoot)
	if err := extractAll(getRes.Body, tmpRoot); err != nil {
		return err
	}

	entries, _ := os.ReadDir(tmpRoot)
	if len(entries) == 0 {
		return errors.New("empty tarball")
	}
	srcRoot := filepath.Join(tmpRoot, entries[0].Name())

	// Stage: README + docs
	stage := tmpRoot + "-stage"
	if err := os.MkdirAll(stage, 0o755); err != nil {
		return err
	}
	_ = copyIfExists(filepath.Join(srcRoot, "README.md"), filepath.Join(stage, "README.md"))
	if _, err := os.Stat(filepath.Join(srcRoot, "docs")); err == nil {
		if err := copyTree(filepath.Join(srcRoot, "docs"), filepath.Join(stage, "docs")); err != nil {
			return err
		}
	}

	// Atomic swap
	active := u.cfg.DataDir
	oldETag, _ := os.ReadFile(u.etagFile)
	_ = os.RemoveAll(active)
	if err := os.Rename(stage, active); err != nil {
		return err
	}
	use := newETag
	if use == "" && len(oldETag) > 0 {
		use = string(oldETag)
	}
	if use != "" {
		_ = os.WriteFile(u.etagFile, []byte(use), 0o644)
	}

	if onSwap != nil {
		return onSwap(active)
	}
	return nil
}

func extractAll(r io.Reader, dst string) error {
	gr, err := gzip.NewReader(r)
	if err != nil {
		return err
	}
	defer gr.Close()

	tr := tar.NewReader(gr)
	for {
		h, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		clean := filepath.Clean(h.Name)
		if strings.HasPrefix(clean, "../") || strings.Contains(clean, "/../") {
			continue
		}
		target := filepath.Join(dst, clean)
		switch h.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0o755); err != nil {
				return err
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return err
			}
			f, err := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, os.FileMode(h.Mode))
			if err != nil {
				return err
			}
			if _, err := io.Copy(f, tr); err != nil {
				f.Close()
				return err
			}
			f.Close()
		case tar.TypeSymlink:
			// ignore for safety
			continue
		}
	}
	return nil
}

func copyIfExists(src, dst string) error {
	if _, err := os.Stat(src); err != nil {
		return nil
	}
	return copyFile(src, dst)
}

func copyFile(src, dst string) error {
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}

func copyTree(src, dst string) error {
	return filepath.Walk(src, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(src, p)
		target := filepath.Join(dst, rel)
		if info.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		return copyFile(p, target)
	})
}
