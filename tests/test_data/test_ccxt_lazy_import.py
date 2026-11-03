"""Isolated CCXT import checks; no exchange, service, or database is contacted."""
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CCXTLazyImportTests(unittest.TestCase):
    def run_script(self, source):
        result = subprocess.run(
            [sys.executable, "-B", "-c", textwrap.dedent(source)],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_import_does_not_attempt_ccxt_and_connect_checks_dependency(self):
        self.run_script('''
            import asyncio
            import importlib.abc
            import sys

            attempts = []
            class BlockCCXT(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == "ccxt" or fullname.startswith("ccxt."):
                        attempts.append(fullname)
                        raise ModuleNotFoundError("CCXT intentionally unavailable")
            sys.meta_path.insert(0, BlockCCXT())
            from services.nexus_data import ccxt_connector as module
            connector = module.CCXTConnector()
            assert attempts == [], attempts
            assert not any(n == "ccxt" or n.startswith("ccxt.") for n in sys.modules)
            assert module.ccxt_async is None and module.ccxt_pro is None
            for _ in range(2):
                try:
                    asyncio.run(connector.connect())
                except RuntimeError as exc:
                    assert str(exc) == "ccxt package is not installed"
                    assert isinstance(exc.__cause__, ImportError)
                else:
                    raise AssertionError("connect did not check dependencies")
            assert len(attempts) == 2, attempts
            assert not connector.connected
        ''')

    def test_lazy_modules_are_reused_by_reconnect(self):
        self.run_script('''
            import asyncio
            from types import SimpleNamespace
            from services.nexus_data import ccxt_connector as module

            calls = []
            instances = []
            class Exchange:
                def __init__(self, config):
                    self.config = config
                    self.markets = {"BTC/USDT": {}}
                    instances.append(self)
                async def load_markets(self):
                    pass
                async def close(self):
                    pass
            async_module = SimpleNamespace(binance=Exchange)
            pro_module = SimpleNamespace(binance=Exchange)
            def fake_import(name):
                calls.append(name)
                return {"ccxt.async_support": async_module, "ccxt.pro": pro_module}[name]
            module.import_module = fake_import
            async def check():
                connector = module.CCXTConnector()
                assert calls == []
                await connector.connect(api_key="test-key", secret="test-secret")
                assert connector.connected
                assert module.ccxt_async is async_module
                assert module.ccxt_pro is pro_module
                assert await connector._reconnect()
                assert len(instances) == 4
                assert all(e.config == {"enableRateLimit": True, "apiKey": "test-key", "secret": "test-secret"} for e in instances)
                assert calls == ["ccxt.async_support", "ccxt.pro"], calls
                await connector.disconnect()
                assert not connector.connected
            asyncio.run(check())
        ''')

    def test_missing_optional_pro_preserves_rest(self):
        self.run_script('''
            import asyncio
            from types import SimpleNamespace
            from services.nexus_data import ccxt_connector as module

            class Exchange:
                def __init__(self, config):
                    self.markets = {}
                async def load_markets(self):
                    pass
                async def close(self):
                    pass
            def fake_import(name):
                if name == "ccxt.pro":
                    raise ImportError("optional pro unavailable")
                assert name == "ccxt.async_support"
                return SimpleNamespace(binance=Exchange)
            module.import_module = fake_import
            async def check():
                connector = module.CCXTConnector()
                await connector.connect()
                assert connector.connected
                assert connector._ws_exchange is None
                assert await connector._reconnect()
                await connector.disconnect()
            asyncio.run(check())
        ''')


if __name__ == "__main__":
    unittest.main()
