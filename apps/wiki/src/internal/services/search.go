package services

// Tiny in-memory search across README + /docs/*.md

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

type Doc struct {
	Path  string // URL path, e.g. "/" or "/guides/getting-started"
	Title string
	Body  string
}

type Index struct {
	docs []Doc
}

func NewIndex(docsRoot string, readmePath string) (*Index, error) {
	var docs []Doc

	// README as home
	if b, err := os.ReadFile(readmePath); err == nil {
		docs = append(docs, Doc{
			Path:  "/",
			Title: extractTitle(string(b)),
			Body:  string(b),
		})
	}

	// Walk docs
	_ = filepath.WalkDir(docsRoot, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(d.Name(), ".md") {
			return err
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(docsRoot, p)
		urlPath := "/" + strings.TrimSuffix(filepath.ToSlash(rel), ".md")
		docs = append(docs, Doc{
			Path:  urlPath,
			Title: extractTitle(string(b)),
			Body:  string(b),
		})
		return nil
	})

	return &Index{docs: docs}, nil
}

func extractTitle(md string) string {
	for _, line := range strings.Split(md, "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "# ") {
			return strings.TrimPrefix(line, "# ")
		}
	}
	return "Untitled"
}

func (idx *Index) Query(q string) []Doc {
	q = strings.ToLower(strings.TrimSpace(q))
	if q == "" {
		return nil
	}
	var out []Doc
	for _, d := range idx.docs {
		if strings.Contains(strings.ToLower(d.Title), q) || strings.Contains(strings.ToLower(d.Body), q) {
			out = append(out, d)
		}
	}
	return out
}
