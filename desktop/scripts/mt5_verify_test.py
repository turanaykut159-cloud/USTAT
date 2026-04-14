"""MT5 verify debug — hangi adimda takiliyor?"""
import json, sys, time, os

log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'mt5_verify_detail.log')

def dlog(msg):
    ts = time.strftime('%H:%M:%S')
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f'{ts} | {msg}\n')
    except:
        pass

dlog('Script basladi')
dlog(f'Python: {sys.executable}')
dlog(f'PID: {os.getpid()}')
dlog(f'CWD: {os.getcwd()}')

try:
    dlog('MetaTrader5 import ediliyor...')
    t0 = time.time()
    import MetaTrader5 as mt5
    dlog(f'import OK ({time.time()-t0:.2f}s)')

    dlog('mt5.initialize() cagiriliyor...')
    t1 = time.time()
    ok = mt5.initialize()
    dlog(f'mt5.initialize() = {ok} ({time.time()-t1:.2f}s)')

    if not ok:
        err = mt5.last_error()
        dlog(f'last_error: {err}')
        print(json.dumps({'connected': False, 'message': f'initialize failed: {err}'}))
        sys.exit(0)

    dlog('mt5.account_info() cagiriliyor...')
    t2 = time.time()
    info = mt5.account_info()
    dlog(f'account_info = {info is not None} ({time.time()-t2:.2f}s)')

    if info is None:
        mt5.shutdown()
        print(json.dumps({'connected': False, 'message': 'account_info None'}))
        sys.exit(0)

    dlog(f'Hesap: {info.login} @ {info.server}, bakiye: {info.balance}')
    print(json.dumps({
        'connected': True,
        'message': 'Baglanti basarili',
        'account': {
            'login': info.login,
            'server': info.server,
            'balance': info.balance,
            'name': info.name,
        }
    }))
    mt5.shutdown()
    dlog('Tamamlandi, shutdown OK')
except Exception as e:
    dlog(f'EXCEPTION: {e}')
    print(json.dumps({'connected': False, 'message': str(e)}))
