import json
from pathlib import Path
import tempfile
import unittest
from guardian.service_endpoint import publish,resolve_port,NAME


class EndpointTests(unittest.TestCase):
    def test_refresh_override_and_missing_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            token=Path(directory)/'token'
            self.assertEqual(resolve_port(token),8765)
            for port in (18001,18002):
                publish(directory,port)
                self.assertEqual(resolve_port(token),port)
                self.assertEqual(resolve_port(token,19000),19000)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()),[NAME])

    def test_malformed_remote_or_oversized_descriptor_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            token=Path(directory)/'token';path=Path(directory)/NAME
            values=[{},None,{'version':1,'host':'example.com','port':8765},
                    {'version':1,'host':'127.0.0.1','port':True},
                    {'version':1,'host':'127.0.0.1','port':'8765'},
                    {'version':1,'host':'127.0.0.1','port':65536}]
            for value in values:
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):resolve_port(token)
            path.write_text(' '*4097)
            with self.assertRaises(ValueError):resolve_port(token)


if __name__=='__main__':unittest.main()
