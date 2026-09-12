package tools

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"golang.org/x/net/html"

	"super-agent/runtime/protocol"
)

const maxBrowserBytes = 2 << 20

type WebSearchTool struct{}
type BrowserFetchTool struct{}

func (WebSearchTool) Spec() protocol.ToolSpec {
	return protocol.ToolSpec{Name: "web_search", Description: "Search the public web.", Risky: true, Parameters: objectSchema(map[string]any{"query": map[string]any{"type": "string"}}, []string{"query"})}
}

func (BrowserFetchTool) Spec() protocol.ToolSpec {
	return protocol.ToolSpec{Name: "browser_fetch", Description: "Fetch and extract text from a public HTTP(S) page.", Risky: true, Parameters: objectSchema(map[string]any{"url": map[string]any{"type": "string"}}, []string{"url"})}
}

func (WebSearchTool) Run(ctx context.Context, call protocol.ToolCall) (string, error) {
	var input struct {
		Query string `json:"query"`
	}
	if err := decodeArgs(call.Input, &input); err != nil {
		return "", err
	}
	input.Query = strings.TrimSpace(input.Query)
	if input.Query == "" {
		return "", errors.New("search query is required")
	}
	endpoint := "https://html.duckduckgo.com/html/?q=" + url.QueryEscape(input.Query)
	content, finalURL, err := fetchPublic(ctx, endpoint)
	if err != nil {
		return "", err
	}
	return extractedPage(finalURL, content), nil
}

func (BrowserFetchTool) Run(ctx context.Context, call protocol.ToolCall) (string, error) {
	var input struct {
		URL string `json:"url"`
	}
	if err := decodeArgs(call.Input, &input); err != nil {
		return "", err
	}
	content, finalURL, err := fetchPublic(ctx, strings.TrimSpace(input.URL))
	if err != nil {
		return "", err
	}
	return extractedPage(finalURL, content), nil
}

func fetchPublic(ctx context.Context, rawURL string) ([]byte, string, error) {
	parsed, err := validatePublicURL(rawURL)
	if err != nil {
		return nil, "", err
	}
	dialer := &net.Dialer{Timeout: 10 * time.Second}
	transport := &http.Transport{DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		host, port, err := net.SplitHostPort(address)
		if err != nil {
			return nil, err
		}
		ips, err := net.DefaultResolver.LookupIP(ctx, "ip", host)
		if err != nil {
			return nil, err
		}
		for _, ip := range ips {
			if !publicIP(ip) {
				return nil, errors.New("browser blocked a private or local address")
			}
		}
		if len(ips) == 0 {
			return nil, errors.New("browser could not resolve host")
		}
		return dialer.DialContext(ctx, network, net.JoinHostPort(ips[0].String(), port))
	}}
	client := &http.Client{Transport: transport, Timeout: 20 * time.Second, CheckRedirect: func(request *http.Request, via []*http.Request) error {
		if len(via) >= 5 {
			return errors.New("too many redirects")
		}
		_, err := validatePublicURL(request.URL.String())
		return err
	}}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, parsed.String(), nil)
	if err != nil {
		return nil, "", err
	}
	request.Header.Set("User-Agent", "Super-Agent/0.1")
	response, err := client.Do(request)
	if err != nil {
		return nil, "", err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, "", fmt.Errorf("HTTP status %s", response.Status)
	}
	content, err := io.ReadAll(io.LimitReader(response.Body, maxBrowserBytes+1))
	if err != nil {
		return nil, "", err
	}
	if len(content) > maxBrowserBytes {
		return nil, "", errors.New("browser response exceeds 2 MiB")
	}
	return content, response.Request.URL.String(), nil
}

func validatePublicURL(rawURL string) (*url.URL, error) {
	parsed, err := url.Parse(rawURL)
	if err != nil || parsed.Hostname() == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") {
		return nil, errors.New("browser URL must be public HTTP(S)")
	}
	host := strings.ToLower(parsed.Hostname())
	if host == "localhost" || strings.HasSuffix(host, ".localhost") {
		return nil, errors.New("browser blocked a private or local address")
	}
	if ip := net.ParseIP(host); ip != nil && !publicIP(ip) {
		return nil, errors.New("browser blocked a private or local address")
	}
	return parsed, nil
}

func publicIP(ip net.IP) bool {
	return ip.IsGlobalUnicast() && !ip.IsPrivate() && !ip.IsLoopback() && !ip.IsLinkLocalUnicast() && !ip.IsLinkLocalMulticast()
}

func extractedPage(rawURL string, content []byte) string {
	root, err := html.Parse(strings.NewReader(string(content)))
	if err != nil {
		return limitText(string(content), 100_000)
	}
	var lines []string
	var walk func(*html.Node)
	walk = func(node *html.Node) {
		if node.Type == html.ElementNode && (node.Data == "script" || node.Data == "style" || node.Data == "noscript") {
			return
		}
		if node.Type == html.TextNode {
			text := strings.Join(strings.Fields(node.Data), " ")
			if text != "" {
				lines = append(lines, text)
			}
		}
		if node.Type == html.ElementNode && node.Data == "a" {
			for _, attribute := range node.Attr {
				if attribute.Key == "href" {
					if target, err := url.Parse(attribute.Val); err == nil {
						base, _ := url.Parse(rawURL)
						lines = append(lines, "[link: "+base.ResolveReference(target).String()+"]")
					}
				}
			}
		}
		for child := node.FirstChild; child != nil; child = child.NextSibling {
			walk(child)
		}
	}
	walk(root)
	result, _ := json.Marshal(map[string]any{"url": rawURL, "content": limitText(strings.Join(lines, "\n"), 100_000)})
	return string(result)
}

func limitText(value string, limit int) string {
	if len(value) <= limit {
		return value
	}
	return value[:limit] + "\n[truncated]"
}
