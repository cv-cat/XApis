package main

import (
	"bytes"
	"compress/gzip"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	tlsclient "github.com/bogdanfinn/tls-client"
	"github.com/bogdanfinn/tls-client/profiles"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func testServer() *server {
	return &server{token: strings.Repeat("secret", 8), clients: map[string]*clientEntry{}, slots: make(chan struct{}, 4)}
}
func call(s *server, p request, token string) *httptest.ResponseRecorder {
	body, _ := json.Marshal(p)
	r := httptest.NewRequest("POST", "/v1/request", bytes.NewReader(body))
	r.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	s.serve(w, r)
	return w
}
func TestAllowlistAndProxy(t *testing.T) {
	for _, v := range []string{"https://x.com/", "https://jf.x.com/a", "https://api.x.com/graphql", "https://abs.twimg.com/a.js", "https://upload.x.com/i/media"} {
		if !allowed(v) {
			t.Fatal(v)
		}
	}
	for _, v := range []string{"http://x.com/", "https://x.com.evil.com/", "https://x.com@evil.com/", "https://127.0.0.1/", "https://x.com:8080/", "file:///etc/passwd"} {
		if allowed(v) {
			t.Fatal(v)
		}
	}
	for _, v := range []string{"http://u:p@proxy:8080", "https://proxy:443", "socks5://127.0.0.1:1080", "socks5h://proxy:1080"} {
		if !validProxy(v) {
			t.Fatal(v)
		}
	}
	for _, v := range []string{"", "http://proxy", "file:///tmp/a", "http://proxy:80/api", "http://proxy:80?password=x"} {
		if validProxy(v) {
			t.Fatal(v)
		}
	}
}
func TestRequiresTokenProxyAndAccount(t *testing.T) {
	s := testServer()
	p := request{Method: "GET", URL: "https://x.com/", Proxy: "http://proxy:8080", Account: "a"}
	if call(s, p, "bad").Code != 401 {
		t.Fatal("missing authorization")
	}
	p.Proxy = ""
	if call(s, p, s.token).Code != 400 {
		t.Fatal("direct traffic allowed")
	}
	p.Proxy = "http://proxy:8080"
	p.Account = ""
	if call(s, p, s.token).Code != 400 {
		t.Fatal("account required")
	}
}
func TestPoolIsolationAndReuse(t *testing.T) {
	s := testServer()
	a, _ := s.client("a", "http://proxy:8080")
	again, _ := s.client("a", "http://proxy:8080")
	b, _ := s.client("b", "http://proxy:8080")
	changed, _ := s.client("a", "http://different:8080")
	if a != again || a == b || a == changed {
		t.Fatal("account/proxy pools not isolated")
	}
	if a.GetCookieJar() != nil {
		t.Fatal("gateway must not share cookie jars")
	}
	if a.GetFollowRedirect() {
		t.Fatal("unsafe redirect forwarding")
	}
}
func fixtureCert(t *testing.T) (tls.Certificate, *x509.CertPool) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "x.com"}, DNSNames: []string{"x.com"}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}, BasicConstraintsValid: true, IsCA: true}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	k, _ := x509.MarshalECPrivateKey(key)
	cert, err := tls.X509KeyPair(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}), pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: k}))
	if err != nil {
		t.Fatal(err)
	}
	roots := x509.NewCertPool()
	roots.AppendCertsFromPEM(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}))
	return cert, roots
}
func TestTLSOverBoundProxyRoundTrip(t *testing.T) {
	cert, roots := fixtureCert(t)
	var connects atomic.Int32
	var hellos atomic.Int32
	upstream := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Cookie") != "auth_token=fixture" {
			t.Error("cookie lost")
		}
		if r.Header.Get("Authorization") != "Bearer X-credential" {
			t.Error("X auth lost")
		}
		if r.URL.Path != "/fixture" {
			t.Error("wrong path")
		}
		w.Header().Add("Set-Cookie", "ct0=updated; Path=/; Secure")
		w.Header().Set("Content-Encoding", "gzip")
		gz := gzip.NewWriter(w)
		gz.Write([]byte(`{"ok":true}`))
		gz.Close()
	}))
	upstream.TLS = &tls.Config{Certificates: []tls.Certificate{cert}, GetConfigForClient: func(hello *tls.ClientHelloInfo) (*tls.Config, error) {
		hellos.Add(1)
		if hello.ServerName != "x.com" {
			t.Error("SNI mismatch")
		}
		if len(hello.CipherSuites) < 10 {
			t.Error("not a browser-like TLS hello")
		}
		return nil, nil
	}}
	upstream.StartTLS()
	defer upstream.Close()
	proxy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "CONNECT" || r.Host != "x.com:443" {
			t.Error("must CONNECT X through proxy")
			http.Error(w, "bad", 400)
			return
		}
		connects.Add(1)
		remote, err := net.Dial("tcp", upstream.Listener.Addr().String())
		if err != nil {
			t.Error(err)
			return
		}
		local, buf, err := w.(http.Hijacker).Hijack()
		if err != nil {
			t.Error(err)
			return
		}
		buf.WriteString("HTTP/1.1 200 Connection Established\r\n\r\n")
		buf.Flush()
		go func() { defer remote.Close(); defer local.Close(); io.Copy(remote, buf) }()
		go func() { defer remote.Close(); defer local.Close(); io.Copy(local, remote) }()
	}))
	defer proxy.Close()
	s := testServer()
	client, err := tlsclient.NewHttpClient(tlsclient.NewNoopLogger(), tlsclient.WithClientProfile(profiles.Chrome_150), tlsclient.WithProxyUrl(proxy.URL), tlsclient.WithTimeoutSeconds(5), tlsclient.WithNotFollowRedirects(), tlsclient.WithTransportOptions(&tlsclient.TransportOptions{RootCAs: roots}))
	if err != nil {
		t.Fatal(err)
	}
	defer client.CloseIdleConnections()
	sum := sha256.Sum256([]byte("fixture\x00" + proxy.URL))
	s.clients[hex.EncodeToString(sum[:])] = &clientEntry{client, time.Now()}
	p := request{Method: "POST", URL: "https://x.com/fixture", Proxy: proxy.URL, Account: "fixture", Headers: map[string]string{"Cookie": "auth_token=fixture", "Authorization": "Bearer X-credential"}, Body: []byte("content")}
	w := call(s, p, s.token)
	if w.Code != 200 {
		t.Fatalf("gateway status %d %s", w.Code, w.Body.String())
	}
	var result response
	if err = json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if result.Status != 200 || string(result.Body) != `{"ok":true}` || len(result.Headers["Set-Cookie"]) != 1 {
		t.Fatalf("response lost: %+v", result)
	}
	if connects.Load() == 0 || hellos.Load() == 0 {
		t.Fatal("proxy or TLS was bypassed")
	}
}
