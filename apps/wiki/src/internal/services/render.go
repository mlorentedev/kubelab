package services

// Server-side Markdown rendering with sanitization.

import (
	"bytes"

	"github.com/microcosm-cc/bluemonday"
	"github.com/yuin/goldmark"
	"github.com/yuin/goldmark/extension"
	"github.com/yuin/goldmark/renderer/html"
)

var (
	md = goldmark.New(
		goldmark.WithExtensions(extension.GFM),
		goldmark.WithRendererOptions(html.WithUnsafe()), // sanitize after
	)
	sanitizer = bluemonday.UGCPolicy()
)

func MarkdownToHTML(input []byte) ([]byte, error) {
	var buf bytes.Buffer
	if err := md.Convert(input, &buf); err != nil {
		return nil, err
	}
	return sanitizer.SanitizeBytes(buf.Bytes()), nil
}
