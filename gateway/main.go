// Internal X-only TLS egress. Credentials remain in the caller, never in logs.
package main

import (
	"bytes"
	"compress/gzip"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	fhttp "github.com/bogdanfinn/fhttp"
	tlsclient "github.com/bogdanfinn/tls-client"
	"github.com/bogdanfinn/tls-client/profiles"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const maxBody = 16 << 20

type request struct {
	Method  string            `json:"method"`
	URL     string            `json:"url"`
	Headers map[string]string `json:"headers"`
	Body    []byte            `json:"body"`
	Proxy   string            `json:"proxy"`
	Account string            `json:"account"`
}
type response struct {
	Status  int                 `json:"status"`
	Headers map[string][]string `json:"headers"`
	Body    []byte              `json:"body"`
}
type clientEntry struct {
	client tlsclient.HttpClient
	used   time.Time
}
type server struct {
	token   string
	mu      sync.Mutex
	clients map[string]*clientEntry
	slots   chan struct{}
}

func allowed(raw string) bool {
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "https" || u.User != nil || u.Fragment != "" || (u.Port() != "" && u.Port() != "443") {
		return false
	}
	host := strings.ToLower(u.Hostname())
	for _, domain := range []string{"x.com", "twitter.com", "twimg.com"} {
		if host == domain || strings.HasSuffix(host, "."+domain) {
			return true
		}
	}
	return false
}
func validProxy(raw string) bool {
	u, err := url.Parse(raw)
	if err != nil || u.Hostname() == "" || u.Port() == "" || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") {
		return false
	}
	return u.Scheme == "http" || u.Scheme == "https" || u.Scheme == "socks5" || u.Scheme == "socks5h"
}
func (s *server) client(account, proxy string) (tlsclient.HttpClient, error) {
	sum := sha256.Sum256([]byte(account + "\x00" + proxy))
	key := hex.EncodeToString(sum[:])
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now()
	if e := s.clients[key]; e != nil {
		e.used = now
		return e.client, nil
	}
	for k, e := range s.clients {
		if now.Sub(e.used) > 15*time.Minute {
			e.client.CloseIdleConnections()
			delete(s.clients, k)
		}
	}
	if len(s.clients) >= 256 {
		var oldest string
		last := now
		for k, e := range s.clients {
			if e.used.Before(last) {
				oldest = k
				last = e.used
			}
		}
		if oldest != "" {
			s.clients[oldest].client.CloseIdleConnections()
			delete(s.clients, oldest)
		}
	}
	proxy = strings.Replace(proxy, "socks5h://", "socks5://", 1)
	client, err := tlsclient.NewHttpClient(tlsclient.NewNoopLogger(), tlsclient.WithClientProfile(profiles.Chrome_150), tlsclient.WithRandomTLSExtensionOrder(), tlsclient.WithProxyUrl(proxy), tlsclient.WithTimeoutSeconds(120), tlsclient.WithNotFollowRedirects())
	if err != nil {
		return nil, err
	}
	s.clients[key] = &clientEntry{client, now}
	return client, nil
}
func (s *server) serve(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if r.Method != "POST" {
		http.Error(w, "method not allowed", 405)
		return
	}
	if subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+s.token)) != 1 {
		http.Error(w, "unauthorized", 401)
		return
	}
	select {
	case s.slots <- struct{}{}:
		defer func() { <-s.slots }()
	default:
		http.Error(w, "gateway busy", 503)
		return
	}
	var input request
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxBody))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&input) != nil || !allowed(input.URL) || !validProxy(input.Proxy) || input.Account == "" || len(input.Account) > 128 || (input.Method != "GET" && input.Method != "POST") {
		http.Error(w, "invalid destination, proxy or account", 400)
		return
	}
	client, err := s.client(input.Account, input.Proxy)
	if err != nil {
		http.Error(w, "proxy initialization failed", 502)
		return
	}
	req, err := fhttp.NewRequestWithContext(r.Context(), input.Method, input.URL, bytes.NewReader(input.Body))
	if err != nil {
		http.Error(w, "invalid request", 400)
		return
	}
	for k, v := range input.Headers {
		lower := strings.ToLower(k)
		if lower == "host" || lower == "connection" || lower == "content-length" || lower == "transfer-encoding" || lower == "proxy-authorization" || strings.ContainsAny(k+v, "\r\n") {
			continue
		}
		req.Header.Set(k, v)
	}
	req.Header.Set("Accept-Encoding", "gzip")
	req.Header[fhttp.HeaderOrderKey] = []string{"sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform", "upgrade-insecure-requests", "user-agent", "accept", "authorization", "x-csrf-token", "x-client-transaction-id", "x-twitter-auth-type", "x-twitter-active-user", "x-twitter-client-language", "content-type", "origin", "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "referer", "accept-encoding", "accept-language", "cookie", "priority"}
	resp, err := client.Do(req)
	if err != nil {
		http.Error(w, "upstream connection failed", 502)
		return
	}
	defer resp.Body.Close()
	var reader io.Reader = resp.Body
	if resp.Header.Get("Content-Encoding") == "gzip" {
		gz, e := gzip.NewReader(resp.Body)
		if e != nil {
			http.Error(w, "invalid gzip response", 502)
			return
		}
		defer gz.Close()
		reader = gz
		resp.Header.Del("Content-Encoding")
	}
	body, err := io.ReadAll(io.LimitReader(reader, maxBody+1))
	if err != nil || len(body) > maxBody {
		http.Error(w, "upstream response exceeded limit or failed", 502)
		return
	}
	resp.Header.Del("Content-Length")
	json.NewEncoder(w).Encode(response{resp.StatusCode, map[string][]string(resp.Header), body})
}
func loadToken() (string, error) {
	if token := os.Getenv("X_GATEWAY_TOKEN"); token != "" {
		if len(token) < 32 {
			return "", errors.New("gateway token too short")
		}
		return token, nil
	}
	path := os.Getenv("X_GATEWAY_TOKEN_FILE")
	if path == "" {
		path = "/shared/gateway.token"
	}
	data, err := os.ReadFile(path)
	if err == nil {
		if len(strings.TrimSpace(string(data))) < 32 {
			return "", errors.New("invalid token file")
		}
		return strings.TrimSpace(string(data)), nil
	}
	if !os.IsNotExist(err) {
		return "", err
	}
	if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return "", err
	}
	secret := make([]byte, 32)
	if _, err = rand.Read(secret); err != nil {
		return "", err
	}
	value := hex.EncodeToString(secret)
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return "", err
	}
	defer file.Close()
	_, err = file.WriteString(value)
	return value, err
}
func main() {
	if len(os.Args) > 1 && os.Args[1] == "healthcheck" {
		client := &http.Client{Timeout: 3 * time.Second}
		resp, err := client.Get("http://127.0.0.1:8090/healthz")
		if err != nil {
			os.Exit(1)
		}
		resp.Body.Close()
		if resp.StatusCode != 200 {
			os.Exit(1)
		}
		return
	}
	token, err := loadToken()
	if err != nil {
		log.Fatal("Gateway secret initialization failed")
	}
	s := &server{token: token, clients: make(map[string]*clientEntry), slots: make(chan struct{}, 64)}
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/request", s.serve)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, `{"status":"ok","profile":"chrome_150","proxy_required":true}`)
	})
	log.Println("XApis TLS gateway listening on :8090 (Chrome 150, mandatory per-account proxy)")
	srv := &http.Server{Addr: ":8090", Handler: mux, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 130 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16384}
	log.Fatal(srv.ListenAndServe())
}
