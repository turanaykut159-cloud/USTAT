# ÜSTAT v5.9 — Dashboard UI Tam Spesifikasyon

**Tarih:** 3 Nisan 2026
**Amaç:** Dashboard yeniden tasarımı için birebir görsel referans dokümanı
**Kaynak:** Kaynak kod analizi (theme.css, Dashboard.jsx, TopBar.jsx, SideNav.jsx, NewsPanel.jsx, NewsPanel.css)

---

## 1. GENEL YAPI (Layout)

```
┌──────────────────────────────────────────────────────────┐
│                      TOP BAR (44px)                       │
├──────────┬───────────────────────────────────────────────┤
│          │                                               │
│  SIDE    │              APP CONTENT                      │
│  NAV     │              (padding: 20px)                  │
│  (200px) │                                               │
│          │  ┌─ Dashboard ──────────────────────────────┐ │
│          │  │ 4 Stat Cards (grid row)                  │ │
│          │  │ Account Strip (6-sütun grid)             │ │
│          │  │ Positions Row (flex, gap 16px)            │ │
│          │  │   ├─ Açık Pozisyonlar (tablo)            │ │
│          │  │   └─ Haber Akışı (panel)                 │ │
│          │  │ Bottom Row (Son İşlemler)                 │ │
│          │  └──────────────────────────────────────────┘ │
│          │                                               │
├──────────┤                                               │
│ Güvenli  │                                               │
│ Kapat    │                                               │
│ Kill-Sw  │                                               │
└──────────┴───────────────────────────────────────────────┘
```

### Ana Konteyner
- `.app-container`: flex column, height 100vh
- `.app-body`: flex row, flex 1, overflow hidden
- `.app-content`: flex 1, padding 20px, overflow-y auto
- `.dashboard`: flex column, gap 16px

### Tema Değişkenleri (Koyu Tema — Varsayılan)

| Değişken | Değer | Kullanım |
|----------|-------|----------|
| `--bg-primary` | `#0d1117` | Sayfa arka planı |
| `--bg-secondary` | `#161b22` | TopBar, SideNav arka planı |
| `--bg-tertiary` | `#21262d` | Hover durumları |
| `--bg-card` | `#1c2128` | Kartlar, şeritler |
| `--bg-hover` | `#21262d` | Hover arka planı |
| `--border` | `#30363d` | Tüm kenarlıklar |
| `--text-primary` | `#e6edf3` | Ana metin rengi |
| `--text-secondary` | `#8b949e` | İkincil metin, etiketler |
| `--text-dim` | `#6e7681` | Soluk metin, suffixler |
| `--accent` | `#58a6ff` | Vurgu rengi (aktif linkler, logo) |
| `--accent-dim` | `rgba(88, 166, 255, 0.15)` | Vurgu arka planı |
| `--profit` | `#3fb950` | Kâr, pozitif değerler, bağlı durum |
| `--loss` | `#f85149` | Zarar, negatif değerler, kopuk durum |
| `--warning` | `#d29922` | Uyarılar |

### Tema Değişkenleri (Açık Tema)

| Değişken | Değer |
|----------|-------|
| `--bg-primary` | `#f6f8fa` |
| `--bg-secondary` | `#ffffff` |
| `--bg-tertiary` | `#e8ebed` |
| `--bg-card` | `#ffffff` |
| `--bg-hover` | `#eaeef2` |
| `--border` | `#d0d7de` |
| `--text-primary` | `#1f2328` |
| `--text-secondary` | `#656d76` |
| `--text-dim` | `#8c959f` |
| `--accent` | `#0969da` |
| `--accent-dim` | `rgba(9, 105, 218, 0.12)` |
| `--profit` | `#1a7f37` |
| `--loss` | `#cf222e` |
| `--warning` | `#9a6700` |

### Global Font

```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
  'Cascadia Code', 'Fira Code', monospace;
```

### Scrollbar

- Width/height: 8px
- Track: `--bg-primary`
- Thumb: `--border`, border-radius 4px
- Thumb hover: `--text-secondary`

---

## 2. TOP BAR

### Konteyner
- Sınıf: `.top-bar`
- Yükseklik: **44px**
- Padding: **6px 16px**
- Background: `var(--bg-secondary)` → `#161b22`
- Border-bottom: 1px solid `var(--border)` → `#30363d`
- Display: flex, justify-content space-between, align-items center
- `-webkit-app-region: drag` (Electron sürükleme)

### Sol Bölüm (`.top-bar-left`)
- Display: flex, align-items center, gap **10px**

#### 2.1 Logo/Başlık
- Eleman: `<h1>`
- Metin: "ÜSTAT"
- Font-size: **16px**
- Color: `var(--accent)` → `#58a6ff`
- Letter-spacing: **1px**
- White-space: nowrap

#### 2.2 Versiyon
- Sınıf: `.version`
- Metin: "v5.9"
- Font-size: **10px**
- Color: `var(--text-secondary)` → `#8b949e`
- Font-weight: 400
- Vertical-align: super

#### 2.3 Phase Badge (Durum Etiketi)
- Sınıf: `.tb-phase`
- Padding: **2px 8px**
- Border-radius: **4px**
- Font-size: **11px**
- Font-weight: **600**
- Letter-spacing: **0.3px**
- Text-transform: uppercase

| Durum | Sınıf | Background | Renk | Metin |
|-------|-------|-----------|------|-------|
| Çalışıyor | `.tb-phase--running` | `rgba(63, 185, 80, 0.15)` | `--profit` (#3fb950) | AKTIF |
| Durdu | `.tb-phase--stopped` | `rgba(139, 148, 158, 0.12)` | `--text-secondary` (#8b949e) | PASİF |
| Bekliyor | `.tb-phase--idle` | `rgba(139, 148, 158, 0.12)` | `--text-secondary` (#8b949e) | BEKLEMEDE |
| Kill-Switch | `.tb-phase--killed` | `rgba(248, 81, 73, 0.15)` | `--loss` (#f85149) | DURDURULDU |
| Hata | `.tb-phase--error` | `rgba(210, 153, 34, 0.15)` | `--warning` (#d29922) | HATA |

#### 2.4 Faz Badge (Kill-Switch Seviyesi)
- Sınıf: `.tb-faz`
- Padding: **2px 8px**
- Border-radius: **4px**
- Font-size: **11px**
- Font-weight: **600**
- Letter-spacing: **0.3px**

| Seviye | Sınıf | Background | Renk |
|--------|-------|-----------|------|
| FAZ 0 | `.tb-faz--level0` | `rgba(63, 185, 80, 0.12)` | `--profit` |
| FAZ 1 | `.tb-faz--level1` | `rgba(210, 153, 34, 0.12)` | `--warning` |
| FAZ 2 | `.tb-faz--level2` | `rgba(248, 81, 73, 0.12)` | `--loss` |
| FAZ 3 | `.tb-faz--level3` | `rgba(248, 81, 73, 0.25)` | `--loss` |

- FAZ 3 animation: `pulse-faz` (2s ease-in-out infinite, opacity 1 → 0.55)
- Kill-Switch sıfırlama butonu (`.tb-ks-reset`): padding 2px 10px, border-radius 4px, font-size 11px, font-weight 600, background `rgba(63, 185, 80, 0.15)`, color `--profit`, hover `rgba(63, 185, 80, 0.3)`, disabled opacity 0.5

#### 2.5 Bağlantı Noktaları (MT5 + Agent)
- Sınıf: `.tb-conn`
- Display: inline-flex, align-items center
- Gap: **5px**
- Font-size: **11px**
- Font-weight: **500**
- Padding: **2px 8px**
- Border-radius: **4px**

**Bağlantı Noktası (Dot):**
- Sınıf: `.tb-conn-dot`
- Width: **7px**, Height: **7px**
- Border-radius: 50%

| Durum | Sınıf | Dot Renk | Metin Renk | Efekt |
|-------|-------|---------|-----------|-------|
| Bağlı | `.tb-conn--on` | `--profit` (#3fb950) | `--profit` | box-shadow: 0 0 4px `--profit` |
| Kopuk | `.tb-conn--off` | `--loss` (#f85149) | `--loss` | Yok |

- Metin: MT5 bağlıysa "MT5", değilse "MT5 ✗". Ajan bağlıysa "Ajan", değilse "Ajan ✗"

### Sağ Bölüm (`.top-bar-right`)
- Display: flex, gap **10px**, align-items center
- Font-size: **13px**

#### 2.6 Finansal Metrikler
- Sınıf: `.tb-metric`
- Display: flex column, align-items flex-end
- Gap: **1px**
- Min-width: **90px**

**Etiket (`.tb-metric-label`):**
- Font-size: **10px**
- Color: `--text-secondary`
- Text-transform: uppercase
- Letter-spacing: **0.4px**
- Font-weight: 500

**Değer (`.tb-metric-value`):**
- Font-size: **14px**
- Font-weight: **600**
- Font-variant-numeric: tabular-nums
- Font-family: 'Cascadia Code', 'Fira Code', monospace
- Letter-spacing: **-0.3px**
- Renk: Değere göre `--profit` veya `--loss` (dinamik)

**Metrikler sırası:** Bakiye → Equity → Floating → Günlük K/Z
- Her metrik arasında `.tb-divider`: width 1px, height 24px, background `--border`

#### 2.7 Pin Butonu (Always on Top)
- Sınıf: `.pin-btn`
- Background: none
- Border: 1px solid transparent
- Border-radius: **4px**
- Font-size: **14px**
- Padding: **2px 6px**
- İkon: 📌 (pinned) / 📍 (unpinned)
- Hover: background `--bg-hover`, border-color `--border`
- Pinned durumu: background `--accent-dim`, border-color `--accent`

#### 2.8 Saat
- Sınıf: `.clock`
- Color: `--text-secondary`
- Font-variant-numeric: tabular-nums
- Font-size: **13px**
- Min-width: **64px**
- Format: "HH:MM:SS" (1 saniye güncelleme)

#### 2.9 Pencere Kontrolleri
- Konteyner: `.window-controls`, flex, gap 0, margin-left 8px

**Butonlar (`.wc-btn`):**
- Width: **40px**, Height: **32px**
- Border: none
- Background: transparent
- Color: `--text-secondary`
- Hover: background `rgba(255, 255, 255, 0.08)`, color `--text-primary`

**Kapat butonu (`.wc-close`):**
- Hover: background `#e81123`, color `#fff`

**Buton ikonları:** ─ (minimize), ☐ (maximize), ✕ (close)

---

## 3. SIDE NAV (Sol Menü)

### Konteyner
- Sınıf: `.side-nav`
- Width: **200px**
- Background: `var(--bg-secondary)` → `#161b22`
- Border-right: 1px solid `var(--border)` → `#30363d`
- Padding: 0
- Flex-shrink: 0
- Display: flex column

### 3.1 Navigasyon Linkleri
- Sınıf: `.side-nav-links`
- List-style: none
- Flex: 1
- Padding: **8px 0**
- Overflow-y: auto

**Her link (`.side-nav-links li a`):**
- Display: flex, align-items center
- Gap: **10px**
- Padding: **10px 16px**
- Color: `var(--text-secondary)` → `#8b949e`
- Text-decoration: none
- Font-size: **13px**
- Transition: all 0.15s
- Border-left: **3px** solid transparent

**Hover:**
- Background: `var(--bg-hover)` → `#21262d`
- Color: `var(--text-primary)` → `#e6edf3`

**Active (seçili sayfa):**
- Color: `var(--accent)` → `#58a6ff`
- Border-left-color: `var(--accent)` → `#58a6ff`
- Background: `rgba(88, 166, 255, 0.05)`

### 3.2 Navigasyon İkonları
- Sınıf: `.nav-icon`
- Font-size: **16px**
- Width: **22px**
- Text-align: center
- Flex-shrink: 0

### 3.3 Navigasyon Etiketleri
- Sınıf: `.nav-label`
- White-space: nowrap
- Overflow: hidden
- Text-overflow: ellipsis

### 3.4 Menü Öğeleri (12 adet)

| Sıra | İkon | Etiket | Yol |
|------|------|--------|-----|
| 1 | 📊 | Dashboard | `/` |
| 2 | 🎯 | Manuel İşlem Paneli | `/manual` |
| 3 | 🔀 | Hibrit İşlem Paneli | `/hybrid` |
| 4 | 🤖 | Otomatik İşlem Paneli | `/auto` |
| 5 | 📋 | İşlem Geçmişi | `/trades` |
| 6 | 🏆 | Performans | `/performance` |
| 7 | 🧠 | ÜSTAT | `/ustat` |
| 8 | 🛡️ | Risk Yönetimi | `/risk` |
| 9 | 📡 | System Monitor | `/monitor` |
| 10 | 🔍 | Hata Takip | `/errors` |
| 11 | 💓 | NABIZ | `/nabiz` |
| 12 | ⚙️ | Ayarlar | `/settings` |

### 3.5 Alt Bölüm (`.side-nav-bottom`)
- Padding: **12px**
- Border-top: 1px solid `var(--border)` → `#30363d`
- Display: flex column
- Gap: **8px**

#### 3.5.1 Güvenli Kapat Butonu
- Sınıf: `.safe-quit-btn`
- Width: 100%
- Display: flex, align-items center, justify-content center
- Gap: **8px**
- Padding: **10px 12px**
- Border: 1px solid `var(--border)` → `#30363d`
- Border-radius: **6px**
- Background: `var(--bg-secondary)` → `#161b22`
- Color: `var(--text-secondary)` → `#8b949e`
- Font-size: **13px**
- Font-weight: **500**
- İkon: 🚪 (font-size 14px)
- Etiket: "Güvenli Kapat"
- Hover: background `--bg-tertiary`, border-color `--text-muted`
- Active: transform scale(0.98)
- 2 adımlı doğrulama modalı tetikler

#### 3.5.2 Kill-Switch Butonu
- Sınıf: `.kill-switch-btn`
- Width: 100%
- Display: flex, align-items center, justify-content center
- Gap: **8px**
- Padding: **10px 12px**
- Border: 1px solid `rgba(248, 81, 73, 0.3)`
- Border-radius: **6px**
- Background: `rgba(248, 81, 73, 0.08)`
- Color: `var(--loss)` → `#f85149`
- Font-size: **13px**
- Font-weight: **600**
- Position: relative
- Overflow: hidden
- İkon: ⛔ (font-size 15px, z-index 1)
- Etiket (`.kill-label`): z-index 1, letter-spacing 0.3px

**Davranış:** 2 saniye basılı tutma gerektirir

**Durumlar:**

| Durum | Etiket | Border | Background |
|-------|--------|--------|-----------|
| Normal | "Kill-Switch" | `rgba(248, 81, 73, 0.3)` | `rgba(248, 81, 73, 0.08)` |
| Hover | "Kill-Switch" | `rgba(248, 81, 73, 0.5)` | `rgba(248, 81, 73, 0.14)` |
| Basılı (`.holding`) | "Basılı tutun..." | `var(--loss)` | `rgba(248, 81, 73, 0.1)` |
| Tetiklendi (`.fired`) | "DURDURULDU!" | `var(--loss)` | `var(--loss)` (tam kırmızı) |

**İlerleme çubuğu (`.kill-progress`):**
- Position: absolute, left 0, top 0
- Height: 100%
- Background: `rgba(248, 81, 73, 0.25)`
- Width: 0% → 100% (2 saniyede, 16ms aralıklarla güncellenir)

---

## 4. CONFIRM MODAL (2 Adım Doğrulama)

### Overlay
- Sınıf: `.confirm-modal-overlay`
- Position: fixed, inset 0
- Z-index: **9999**
- Display: flex, align-items center, justify-content center
- Background: `rgba(0, 0, 0, 0.65)`
- Backdrop-filter: `blur(4px)`
- Animation: fade-in 0.2s ease-out

### Kart
- Sınıf: `.confirm-modal-card`
- Min-width: **360px**, Max-width: **440px**
- Padding: **24px**
- Background: `var(--bg-card)` → `#1c2128`
- Border: 1px solid `var(--border)` → `#30363d`
- Border-radius: **10px**
- Box-shadow: `0 12px 40px rgba(0, 0, 0, 0.4)`
- Animation: slide-in 0.25s ease-out (scale 0.96 → 1, translateY -8px → 0)

### Başlık
- Font-size: **17px**, font-weight **600**, color `--text-primary`
- Letter-spacing: **0.3px**, margin-bottom: **14px**

### Mesaj
- Font-size: **14px**, line-height **1.5**, color `--text-secondary`
- White-space: pre-line, margin-bottom: **22px**

### Butonlar
- Konteyner: flex, justify-content flex-end, gap **10px**
- Her buton: padding **10px 20px**, font-size **13px**, font-weight **500**, border-radius **6px**

| Varyant | Background | Border |
|---------|-----------|--------|
| Primary | `var(--accent)` | `var(--accent)` |
| Warning | `#c17a1a` | `#c17a1a` |
| Danger | `#da3633` | `#da3633` |
| Cancel | `var(--bg-tertiary)` | `var(--border)` |

---

## 5. DASHBOARD İÇERİĞİ

Dashboard sayfasının tüm bileşenleri. Üstten alta sıra:

### 5.1 Stale/Reconnect Banner (Koşullu)
- Sınıf: `.dash-stale-banner`
- Background: `var(--warning)` → `#d29922` (tam opak sarı)
- Color: `#1a1a2e` (koyu metin)
- Text-align: center
- Padding: **6px 12px**
- Font-size: **0.82rem**
- Font-weight: **600**
- Border-radius: **6px**
- Margin-bottom: **8px**
- Animation: `stale-pulse` 2s ease-in-out infinite (opacity 1 → 0.7)

### 5.2 API Error Banner (Koşullu)
- Sınıf: `.dash-api-error-banner`
- Background: `rgba(231, 76, 60, 0.15)`
- Color: `var(--loss)` → `#f85149`
- Text-align: center
- Padding: **8px 12px**
- Font-size: **0.82rem**
- Font-weight: **600**
- Border-radius: **6px**
- Margin-bottom: **8px**
- Border: 1px solid `rgba(231, 76, 60, 0.3)`

### 5.3 Rejim Göstergesi
- Sınıf: `.dash-regime`
- Margin-bottom: **16px**
- Padding-bottom: **14px**
- Border-bottom: 1px solid `var(--border)`

**Başlık:** "Piyasa Rejimi" + Onaylanmamış badge (koşullu)
- `.dash-unapproved-badge`: inline-block, background `--warning`, color `#1a1a2e`, font-size 0.7rem, font-weight 700, padding 2px 8px, border-radius 10px

**Rejim Badge (`.regime-badge`):**
- Display: inline-flex, align-items center
- Gap: **8px**
- Padding: **8px 16px**
- Border-radius: **6px**
- Font-size: **15px**
- Font-weight: **600**
- Letter-spacing: **0.5px**
- Margin-top: **6px**

**Rejim Dot (`.regime-dot`):**
- Width: **8px**, Height: **8px**, border-radius 50%

**Güven Oranı (`.regime-conf`):**
- Font-size: **12px**, opacity 0.7, font-weight 400, margin-left 4px

### 5.4 Stat Cards Row (4 Kart)

#### Konteyner
- Sınıf: `.dash-stats-row`
- Display: grid
- Grid-template-columns: **repeat(4, 1fr)**
- Gap: **12px**

#### Her Kart
- Sınıf: `.dash-stat-card`
- Background: `var(--bg-card)` → `#1c2128`
- Border: 1px solid `var(--border)` → `#30363d`
- Border-radius: **8px**
- Padding: **14px 16px**
- Display: flex column
- Gap: **6px**

**Üst satır (`.dash-stat-top`):** flex, align-items center, gap 6px

**İkon (`.dash-stat-icon`):** font-size **15px**

**Etiket (`.dash-stat-label`):**
- Font-size: **12px**
- Color: `var(--text-secondary)` → `#8b949e`
- Text-transform: **uppercase**
- Letter-spacing: **0.4px**
- Font-weight: **500**

**Değer (`.dash-stat-value`):**
- Font-size: **26px**
- Font-weight: **700**
- Font-variant-numeric: tabular-nums
- Font-family: **'Cascadia Code', 'Fira Code', monospace**
- Letter-spacing: **-0.5px**
- Line-height: **1.1**
- Renk: Değere göre dinamik (`--profit`, `--loss`, veya `--text-primary`)

**Alt metin (`.dash-stat-sub`):**
- Font-size: **11px**
- Color: `var(--text-secondary)` → `#8b949e`
- Letter-spacing: **0.2px**

#### 4 Kart İçeriği

| # | İkon | Etiket | Değer Formatı | Alt Metin |
|---|------|--------|--------------|-----------|
| 1 | 📈 | GÜNLÜK K/Z | ₺ formatı, renk kâr/zarar | Son güncelleme saati |
| 2 | 📊 | TOPLAM K/Z | ₺ formatı, renk kâr/zarar | İşlem sayısı |
| 3 | 🎯 | BAŞARI ORANI | % formatı | Kazanç/Kayıp adet |
| 4 | ⚡ | AKTİF POZİSYON | Adet sayısı | Kontrat isimleri |

### 5.5 Hesap Durumu Şeridi (Account Strip)

#### Konteyner
- Sınıf: `.dash-account-strip`
- Display: grid
- Grid-template-columns: **repeat(6, 1fr)**
- Gap: **10px**
- Margin-bottom: **16px**
- Background: `var(--bg-card)` → `#1c2128`
- Border: 1px solid `var(--border)` → `#30363d`
- Border-radius: **8px**
- Padding: **10px 16px**

#### Her Alan (`.dash-account-item`)
- Display: flex column
- Gap: **2px**

**Etiket (`.dash-account-label`):**
- Font-size: **11px**
- Color: `var(--text-secondary)` → `#8b949e`
- Text-transform: **uppercase**
- Letter-spacing: **0.3px**

**Değer (`.dash-account-value`):**
- Font-size: **15px**
- Font-weight: **600**
- Font-family: **'Cascadia Code', 'Fira Code', monospace**

**Suffix (`.dash-account-suffix`):**
- Font-size: **11px**
- Font-weight: **400**
- Color: `var(--text-dim)` → `#6e7681`
- Margin-left: **2px**

#### 6 Alan İçeriği

| # | Etiket | Değer Formatı | Suffix |
|---|--------|--------------|--------|
| 1 | BAKİYE | ₺ formatı | TL |
| 2 | EQUITY | ₺ formatı | TL |
| 3 | FLOATING | ₺ formatı (renk: kâr/zarar) | TL |
| 4 | SERBEST MARJİN | ₺ formatı | TL |
| 5 | MARJİN SEVİYESİ | % formatı | % |
| 6 | GÜNLÜK İŞLEM | Adet / Limit formatı | — |

### 5.6 Pozisyon Satırı (`.dash-positions-row`)

#### Konteyner
- Display: flex
- Gap: **16px**
- Margin-bottom: **16px**

İki bileşen yan yana: Açık Pozisyonlar Tablosu + Haber Paneli

---

### 5.7 Açık Pozisyonlar Kartı

#### Kart (`.dash-card .dash-card--full`)
- Background: `var(--bg-card)` → `#1c2128`
- Border: 1px solid `var(--border)` → `#30363d`
- Border-radius: **8px**
- Padding: **14px 16px**
- Flex: 1, min-width 0

#### Kart Başlığı (`.dash-card-header`)
- Display: flex, justify-content space-between, align-items center
- Margin-bottom: **12px**

**Başlık (`.dash-card h3`):**
- Font-size: **12px**
- Color: `var(--text-secondary)` → `#8b949e`
- Text-transform: **uppercase**
- Letter-spacing: **0.5px**
- Font-weight: **600**
- Metin: "AÇIK POZİSYONLAR"

**Sağ taraf (`.dash-card-header-right`):**
- Pozisyon sayısı badge (`.dash-card-badge`):
  - Background: `#30363d`
  - Padding: **2px 10px**
  - Border-radius: **12px**
  - Font-size: **13px**
  - Color: `--text-secondary`

- Marjin badge (`.dash-margin-badge`):
  - Padding: **2px 10px**
  - Border-radius: **12px**
  - Font-size: **12px**
  - Font-weight: **500**
  - Normal: background `rgba(63, 185, 80, 0.1)`, color `--profit`
  - Warn: background `rgba(210, 153, 34, 0.1)`, color `--warning`
  - Danger: background `rgba(248, 81, 73, 0.1)`, color `--loss`

#### Pozisyon Tablosu (`.dash-positions-table`)
- Width: 100%
- Border-collapse: collapse
- Font-size: **13px**

**Tablo Başlıkları (th):**
- Text-align: left
- Padding: **8px 10px**
- Color: `--text-secondary` → `#8b949e`
- Font-weight: **600**
- Font-size: **11px**
- Text-transform: **uppercase**
- Letter-spacing: **0.5px**
- Border-bottom: 1px solid `--border`

**Sütunlar:** Kontrat | Yön | Lot | Giriş | Güncel | SL | TP | K/Z | K/Z %

**Tablo Hücreleri (td):**
- Padding: **8px 10px**
- Border-bottom: 1px solid `#21262d`

**Satır hover:**
- Background: `rgba(88, 166, 255, 0.04)`

**Yön Badge (`.dir-badge`):**
- Display: inline-block
- Padding: **1px 6px**
- Border-radius: **3px**
- Font-size: **10px**
- Font-weight: **600**
- Letter-spacing: **0.3px**
- BUY: background `rgba(63, 185, 80, 0.12)`, color `--profit`
- SELL: background `rgba(248, 81, 73, 0.12)`, color `--loss`

**Footer satır (`.dash-positions-footer td`):**
- Padding: **10px 10px**
- Border-top: **2px** solid `--border`
- Border-bottom: none

**Boş durum (`.dash-positions-empty`):**
- Text-align: center
- Padding: **40px 0**
- Color: `--text-secondary`
- Font-size: **14px**
- Emoji font-size: **24px**, margin-right 8px

---

### 5.8 Haber Paneli (News Panel)

#### Konteyner (`.news-panel`)
- Background: `var(--surface)` fallback `#1e1e2e` (genelde `--bg-card` kullanılır)
- Border: 1px solid `var(--border)` fallback `#333`
- Border-radius: **8px**
- Padding: **12px**
- Margin-bottom: **12px**
- Boş durumda: opacity 0.6

#### 5.8.1 Başlık Satırı (`.news-header`)
- Display: flex, align-items center
- Gap: **8px**
- Margin-bottom: **8px**
- Padding-bottom: **6px**
- Border-bottom: 1px solid `var(--border)`

**Başlık (`.news-title`):**
- Font-weight: **600**
- Font-size: **14px**
- Color: `--text-primary`
- İçerik: 📰 emoji + "Haber Akışı"

**Aktif Sayısı (`.news-count`):**
- Font-size: **12px**
- Color: `--text-secondary`
- Background: `--bg-secondary`
- Padding: **2px 8px**
- Border-radius: **10px**

**Severity Badge (`.news-severity-badge`):**
- Font-size: **11px**
- Font-weight: **600**
- Padding: **2px 6px**
- Border-radius: **4px**

**Durum Noktası (`.news-status-dot`):**
- Width: **8px**, Height: **8px**
- Border-radius: 50%
- Margin-left: auto
- Idle: `#666`
- Active: `#4caf50` + `pulse-dot` animasyonu (2s infinite, opacity 1 → 0.5)

#### 5.8.2 Sentiment Özet Bar (`.news-sentiment-bar`)
- Display: flex
- Gap: **8px**
- Margin-bottom: **8px**

**Her Chip (`.news-sentiment-chip`):**
- Font-size: **12px**
- Padding: **3px 8px**
- Border-radius: **4px**
- Font-weight: **500**

| Sentiment | Background | Renk | Etiket |
|-----------|-----------|------|--------|
| Positive | `rgba(76, 175, 80, 0.15)` | `#4caf50` | ▲ En İyi: [sembol] |
| Mild-positive | `rgba(139, 195, 74, 0.15)` | `#8bc34a` | — |
| Neutral | `rgba(158, 158, 158, 0.15)` | `#9e9e9e` | — |
| Mild-negative | `rgba(255, 152, 0, 0.15)` | `#ff9800` | — |
| Negative | `rgba(244, 67, 54, 0.15)` | `#f44336` | ▼ En Kötü: [sembol] |

#### 5.8.3 Haber Listesi (`.news-list`)
- Display: flex column
- Gap: **6px**
- Max-height: **320px**
- Overflow-y: auto
- Maks **8 haber** gösterilir

#### 5.8.4 Her Haber Öğesi (`.news-item`)
- Background: `var(--bg-secondary)` fallback `#2a2a3e`
- Border-radius: **6px**
- Padding: **8px 10px**
- Border-left: **3px** solid transparent
- Transition: border-color 0.2s

**Sentiment'e göre sol border rengi:**

| Sınıf | Border Renk |
|-------|-------------|
| `.news-positive` | `#4caf50` |
| `.news-mild-positive` | `#8bc34a` |
| `.news-neutral` | `#9e9e9e` |
| `.news-mild-negative` | `#ff9800` |
| `.news-negative` | `#f44336` |

**Üst satır (`.news-item-top`):** flex, align-items center, gap 6px, margin-bottom 4px

- **Saat (`.news-time`):** font-size 11px, color `--text-secondary`, font-family monospace
- **Kategori Badge (`.news-cat-badge`):**
  - Font-size: **10px**, font-weight **600**, padding **1px 6px**, border-radius **3px**
  - Text-transform: **uppercase**

  | Kategori | Sınıf | Background | Renk |
  |----------|-------|-----------|------|
  | Jeopolitik | `.cat-jeopolitik` | `rgba(244, 67, 54, 0.2)` | `#ef9a9a` |
  | Ekonomik | `.cat-ekonomik` | `rgba(33, 150, 243, 0.2)` | `#90caf9` |
  | Sektörel | `.cat-sektorel` | `rgba(255, 193, 7, 0.2)` | `#ffe082` |
  | Şirket | `.cat-sirket` | `rgba(76, 175, 80, 0.2)` | `#a5d6a7` |
  | Genel | `.cat-genel` | `rgba(158, 158, 158, 0.2)` | `#bdbdbd` |

- **Severity Badge (`.news-sev-badge`):**
  - Font-size: **10px**, font-weight **600**, padding **1px 5px**, border-radius **3px**

  | Seviye | Sınıf | Background | Renk |
  |--------|-------|-----------|------|
  | Critical | `.badge-critical` | `rgba(211, 47, 47, 0.3)` | `#ef5350` |
  | High | `.badge-high` | `rgba(255, 87, 34, 0.3)` | `#ff7043` |
  | Medium | `.badge-medium` | `rgba(255, 152, 0, 0.3)` | `#ffa726` |
  | Low | `.badge-low` | `rgba(255, 193, 7, 0.2)` | `#ffca28` |
  | None | `.badge-none` | display none | — |

- **Yaş (`.news-age`):** font-size 11px, color `#888`, margin-left auto. Format: "Xdk", "Xsn", "Xsa"

**Başlık (`.news-headline`):**
- Font-size: **13px**
- Color: `--text-primary`
- Line-height: **1.35**
- Margin-bottom: **4px**

**Alt satır (`.news-item-bottom`):** flex, align-items center, gap 6px, flex-wrap wrap

- **Skor (`.news-score`):**
  - Font-size: **12px**, font-weight **600**, font-family monospace
  - Padding: **1px 5px**, border-radius **3px**
  - Sentiment'e göre renk/background (üstteki chip renkleriyle aynı)

- **Güven (`.news-confidence`):** font-size 11px, color `#888`

- **Sembol Etiketleri (`.news-symbol-tag`):**
  - Font-size: **10px**, font-weight **600**
  - Padding: **1px 5px**, border-radius **3px**
  - Background: `rgba(46, 117, 182, 0.2)`, color `#5b9bd5`

- **Global Etiketi (`.news-global-tag`):**
  - Font-size: **11px**, padding **1px 5px**, border-radius **3px**
  - Background: `rgba(156, 39, 176, 0.2)`, color `#ce93d8`
  - İçerik: 🌍

- **Lot Uyarısı (`.news-lot-warn`):**
  - Font-size: **11px**, font-weight **600**
  - Padding: **1px 5px**, border-radius **3px**
  - Background: `rgba(244, 67, 54, 0.2)`, color `#f44336`

#### 5.8.5 Boş Durum
- Sınıf: `.news-empty-msg`
- Text-align: center
- Font-size: **13px**
- Color: `--text-secondary`
- Padding: **16px 0**

---

### 5.9 Son İşlemler (Bottom Row)

#### Konteyner (`.dash-bottom-row`)
- Display: grid
- Grid-template-columns: **1fr** (tam genişlik)
- Gap: **12px**

#### Kart
- `.dash-card` stili (aynı: bg-card, border, border-radius 8px, padding 14px 16px)
- Başlık: "SON İŞLEMLER" (`.dash-card h3` stili)

#### Son İşlemler Tablosu (`.dash-trades-table`)
- Width: 100%
- Border-collapse: collapse
- Font-size: **12px**

**Tablo Başlıkları (th):**
- Font-size: **10px**
- Color: `--text-secondary`
- Text-transform: **uppercase**
- Letter-spacing: **0.4px**
- Padding: **6px 8px**
- Border-bottom: 1px solid `--border`
- Font-weight: **600**
- Text-align: left

**Sütunlar:** Tarih | Kontrat | Yön | Lot | Giriş | Çıkış | K/Z | K/Z % | Strateji

**Tablo Hücreleri (td):**
- Padding: **7px 8px**
- Border-bottom: 1px solid `rgba(48, 54, 61, 0.5)`
- Son satır: border-bottom none

**Mono değerler (`.dash-trades-table .mono`):**
- Font-family: **'Cascadia Code', 'Fira Code', monospace**
- Font-variant-numeric: tabular-nums
- Font-size: **12px**

**Soluk metin (`.text-dim`):** color `--text-secondary`

**Boş durum (`.dash-empty-msg`):**
- Color: `--text-secondary`
- Font-size: **13px**
- Opacity: **0.5**
- Padding: **20px 0**
- Text-align: center

---

### 5.10 Top 5 Kontrat Listesi

#### Konteyner (`.dash-top5`)
- Margin-top: 0

**Liste (`.top5-list`):**
- List-style: none
- Display: flex column
- Gap: **6px**

**Her öğe (`.top5-item`):**
- Display: grid
- Grid-template-columns: **28px 1fr 46px 44px 80px**
- Align-items: center
- Gap: **8px**
- Padding: **6px 0**

**Sıra (`.top5-rank`):**
- Font-size: **11px**
- Color: `--text-secondary`
- Font-weight: **600**
- Text-align: center

---

## 6. VERİ AKIŞI VE GÜNCELLEME ZAMANLARI

| Veri Kaynağı | Yöntem | Aralık |
|-------------|--------|--------|
| Hesap bilgileri | REST polling (`/status` + `/account`) | **10 saniye** |
| Açık pozisyonlar | REST polling (`/positions`) | **10 saniye** |
| Son işlemler | REST polling (`/trades`) | **10 saniye** |
| Equity/Bakiye | WebSocket (`live_equity`) | Anlık |
| Sistem durumu | WebSocket (`status_update`) | Anlık |
| Pozisyon değişimi | WebSocket (`position_update`) | Anlık |
| Hibrit durum | WebSocket (`hybrid_update`) | Anlık |
| Haberler | WebSocket (`news_update`) | Anlık |
| Bildirimler | WebSocket (`notification`) | Anlık |
| Ajan durumu | REST polling (`/agent_ping` proxy) | **10 saniye** |
| Saat | `setInterval` | **1 saniye** |

---

## 7. YÜKLEME VE HATA DURUMLARI

### Yükleniyor
- `.dash-loading-wrap`: padding 40px 20px, text-align center
- `.dash-loading`: color `--text-secondary`
- `.tb-loading`: font-size 12px, color `--text-secondary`, margin-left 8px

### API Bağlantı Kesilmesi
- Stale banner görünür (5.1'deki sarı banner)
- 3× ardışık hata sonrası veri temizlenir
- WebSocket otomatik yeniden bağlanır

---

## 8. RESPONSIVE DAVRANIŞLAR

- Ana layout flex-based, sabit sidebar (200px)
- Dashboard grid kartları repeat(4, 1fr) — ekran küçüldüğünde sıkışır
- Pozisyon tablosu taşma yok (min-width 0 ile flex-shrink)
- Haber listesi max-height 320px ile scroll
- Sidebar linkleri text-overflow ellipsis ile kesilir
- Window controls sadece Electron'da görünür (frameless)
