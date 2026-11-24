"""Optional loopback-only fixture endpoint; accepts a fixed synthetic schema."""
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,body):
        raw=json.dumps(body).encode();self.send_response(status)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        self.reply(200,{'service':'guardian-showcase','synthetic':True}) if self.path=='/health' else self.reply(404,{'error':'not found'})
    def do_POST(self):
        try:
            self.connection.settimeout(3)
            size=int(self.headers.get('Content-Length','0'))
            if self.path!='/ingest' or not 0<size<2048:raise ValueError()
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict) or set(data)!={'demo','client','message'}:raise ValueError()
            if data['demo']!='guardian-showcase' or data['client'] not in ('claude-workspace','opencode-workspace') or data['message']!='synthetic local request':raise ValueError()
            self.reply(200,{'accepted':True,'synthetic':True,'client':data['client']})
        except (ValueError,TypeError,OSError):self.reply(400,{'accepted':False})


if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',18765),Handler)
    server.timeout=1
    print('Synthetic fixture: http://127.0.0.1:18765',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
