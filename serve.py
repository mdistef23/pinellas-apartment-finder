import http.server, socketserver, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control","no-store, no-cache, must-revalidate")
        self.send_header("Pragma","no-cache"); self.send_header("Expires","0")
        super().end_headers()
    def log_message(self,*a): pass
socketserver.TCPServer.allow_reuse_address=True
with socketserver.TCPServer(("127.0.0.1",8770),H) as s:
    s.serve_forever()
