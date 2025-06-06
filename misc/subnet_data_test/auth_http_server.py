import http.server
import socketserver
import base64
import sys
import argparse
import signal
import os

class AuthHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler with basic authentication."""
    
    def __init__(self, *args, username, password, directory=None, **kwargs):
        self.AUTH_KEY = base64.b64encode(f"{username}:{password}".encode()).decode()
        # Set the directory directly
        if directory:
            os.chdir(directory)
        super().__init__(*args, **kwargs)

    def do_AUTHHEAD(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Protected"')
        self.send_header("Content-type", "text/html")
        self.end_headers()

    def do_GET(self):
        auth_header = self.headers.get("Authorization")
        if auth_header != f"Basic {self.AUTH_KEY}":
            self.do_AUTHHEAD()
            self.wfile.write(b"Authentication required.")
            return
        super().do_GET()

def run_server(port, directory, username, password):
    handler = lambda *args, **kwargs: AuthHandler(
        *args, username=username, password=password, directory=directory, **kwargs
    )
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"Serving HTTP on port {port} with directory {directory}")
        
        def shutdown_server(signal, frame):
            print("\nShutting down server...")
            httpd.shutdown()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, shutdown_server)
        signal.signal(signal.SIGTERM, shutdown_server)

        httpd.serve_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run HTTP server with basic authentication")
    parser.add_argument("port", type=int, help="Port to run the server on")
    parser.add_argument("directory", type=str, help="Directory to serve")
    parser.add_argument("username", type=str, help="Username for authentication")
    parser.add_argument("password", type=str, help="Password for authentication")
    args = parser.parse_args()

    # Change directory before starting the server
    os.chdir(args.directory)
    run_server(args.port, args.directory, args.username, args.password)
