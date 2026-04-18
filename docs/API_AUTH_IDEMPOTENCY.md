# API Auth + Idempotency Rehberi (v6.2.0)

**Kapsam:** #261 `require_localhost_and_token` + #267 Idempotency-Key header
**Kritik endpoint'ler (5):**
1. `POST /api/killswitch`
2. `POST /api/manual-trade/execute`
3. `POST /api/hybrid/transfer`
4. `POST /api/hybrid/remove`
5. `POST /api/positions/close`

---

## 1. Authorization

### 1.1 Localhost guard (her zaman aktif)

Kritik endpoint'lere yalnızca `127.0.0.1`, `::1` veya `localhost`'dan gelen istekler geçer. Harici IP → **403 Forbidden**.

### 1.2 Token (opsiyonel, production önerilen)

**Kurulum:**

```json
// config/default.json
{
  "api": {
    "auth_token": "buraya-guclu-rastgele-bir-dizgi-koy"
  }
}
```

veya ortam değişkeni:

```bash
set USTAT_API_TOKEN=buraya-guclu-rastgele-bir-dizgi-koy
```

**Öncelik:** `config.api.auth_token` → `USTAT_API_TOKEN` env → boş (yalnızca localhost).

**Token boşsa** guard sadece localhost kontrolü yapar. Token dolduğunda her istekte `X-USTAT-TOKEN` header zorunlu olur.

### 1.3 İstemci (Electron) tarafı

`desktop/src/services/api.js` fetch header'larına:

```js
headers: {
  'Content-Type': 'application/json',
  'X-USTAT-TOKEN': localStorage.getItem('ustat_api_token') || '',
}
```

Başka istemci (cURL, Postman) için:

```bash
curl -X POST http://localhost:8000/api/killswitch \
  -H "Content-Type: application/json" \
  -H "X-USTAT-TOKEN: $USTAT_API_TOKEN" \
  -d '{"action":"acknowledge","user":"TURAN"}'
```

### 1.4 Hata yanıtları

- **403** — `{"detail":"Yalnizca localhost. Gelen IP: x.x.x.x"}`
- **401** — `{"detail":"Gecersiz veya eksik X-USTAT-TOKEN header"}`

---

## 2. Idempotency-Key

Aynı işlemin duplicate çağrısını engellemek için. Örneğin butona çift tıklama, network retry, reconnect.

### 2.1 Kullanım

İstemci her istek için UUID üretir:

```js
const idemKey = crypto.randomUUID();
await fetch('/api/manual-trade/execute', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-USTAT-TOKEN': token,
    'Idempotency-Key': idemKey,
  },
  body: JSON.stringify({symbol: 'F_AKBNK', direction: 'BUY', lot: 1}),
});
```

### 2.2 Davranış

- **İlk istek:** işlem çalışır, sonuç 60 saniye cache'lenir.
- **Aynı `Idempotency-Key` ile 2. istek (60sn içinde):** cached sonuç döner — işlem TEKRAR ÇALIŞMAZ.
- **60sn sonra:** cache expire, 2. istek normal çalışır (yeni işlem).

### 2.3 Cache yapısı

- **TTL:** 60 saniye
- **Key uzunluk sınırı:** 128 karakter
- **Storage:** in-memory (process ölünce kaybolur — bilinçli; cache crash-safety kritik değil)
- **Temizlik:** her store çağrısında expired girişler otomatik silinir

### 2.4 Hangi endpoint'lerde

Şu anda 5 kritik endpoint'in hepsi idempotency-aware:

| Endpoint | Cached response |
|---|---|
| `POST /killswitch` | KillSwitchResponse (sadece başarılı activate/ack) |
| `POST /manual-trade/execute` | ManualTradeExecuteResponse |
| `POST /hybrid/transfer` | HybridTransferResponse |
| `POST /hybrid/remove` | HybridRemoveResponse |
| `POST /positions/close` | ClosePositionResponse |

### 2.5 Best practices

- **UUID kullan** (`crypto.randomUUID()` veya `uuid.v4()`). Tahmin edilebilir key (counter) YAPMA.
- **Retry loop'ta aynı key kullan**. Her retry yeni key kullanırsan idempotency koruma devre dışı kalır.
- **Farklı işlem için farklı key**. Yanlışlıkla aynı key ile farklı symbol → cache karışıklığı.

---

## 3. Güvenlik notları

1. **Token'ı asla commit'leme.** `config/default.json` git'te ama `auth_token` boş default. Üretimde env override kullan.
2. **Port expose etme.** ÜSTAT API default `127.0.0.1:8000` bind — dışarı açılmamalı.
3. **Test süresinde token kapalı kalabilir** (sadece localhost yeterli). Production'a geçişte set et.
4. **Electron + engine aynı makinede** çalıştığı için CORS yok, yalnızca header auth.

---

## 4. Hızlı test

```bash
# Test 1: localhost + token yok (auth boş)
curl -X POST http://127.0.0.1:8000/api/killswitch \
  -H "Content-Type: application/json" \
  -d '{"action":"acknowledge","user":"test"}'
# -> 200 (token set edilmediği için)

# Test 2: token set + yanlış token
# (önce config.api.auth_token = "abc" yap + restart)
curl -X POST http://127.0.0.1:8000/api/killswitch \
  -H "X-USTAT-TOKEN: wrong" -H "Content-Type: application/json" \
  -d '{"action":"acknowledge","user":"test"}'
# -> 401

# Test 3: idempotency
KEY=$(uuidgen)
curl -X POST http://127.0.0.1:8000/api/manual-trade/execute \
  -H "Idempotency-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"symbol":"F_AKBNK","direction":"BUY","lot":1,"sl":0,"tp":0}'
# İlk istek: yeni trade
# Aynı komut tekrar: cached — YENİ trade AÇILMAZ.
```

---

## 5. Referans

- **Implementation:** `api/deps.py::require_localhost_and_token`, `check_idempotency`, `get_idempotent_response`, `store_idempotent_response`
- **Test:** `tests/critical_flows/test_op_n_behavior.py::test_idempotency_cache_roundtrip`
- **Tarihçe:** #261 (auth), #267 (idempotency altyapı), yaygınlaştırma
