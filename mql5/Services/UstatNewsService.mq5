//+------------------------------------------------------------------+
//|                                          UstatNewsService.mq5     |
//|                            ÜSTAT v5.7.1 — MT5 Haber Servisi       |
//|                                                                    |
//|  MT5 Economic Calendar verilerini JSON dosyasına yazar.            |
//|  Python tarafında MT5FileProvider bu dosyayı okur.                 |
//|                                                                    |
//|  Kurulum:                                                          |
//|    1. Bu dosyayı MQL5/Services/ altına kopyala                     |
//|    2. MetaEditor'da derle (Ctrl+F7)                                |
//|    3. Navigator → Services → UstatNewsService sağ tık → Start      |
//|                                                                    |
//|  Çıktı: %APPDATA%\MetaQuotes\Terminal\Common\Files\ustat_news.json|
//+------------------------------------------------------------------+
#property service
#property copyright "ÜSTAT Trading System"
#property version   "1.00"
#property description "MT5 takvim haberlerini JSON olarak dışa aktarır"

//--- Ayarlar
input int    InpCheckIntervalSec = 10;      // Kontrol aralığı (saniye)
input int    InpLookbackHours    = 24;      // Geriye bakış süresi (saat)
input int    InpLookaheadHours   = 12;      // İleriye bakış süresi (saat)
input string InpFileName         = "ustat_news.json"; // Çıktı dosya adı
input string InpCurrencyFilter   = "TRY,USD,EUR";     // Takip edilecek para birimleri (virgülle)
input int    InpMinImportance    = 1;       // Minimum önem seviyesi (0=Yok, 1=Düşük, 2=Orta, 3=Yüksek)

//--- Sabitler
#define JSON_BUFFER_SIZE 65536
#define MAX_EVENTS       200

//+------------------------------------------------------------------+
//| Haber önem seviyesini sayıya çevir                                |
//+------------------------------------------------------------------+
int ImportanceToInt(ENUM_CALENDAR_EVENT_IMPORTANCE importance)
  {
   switch(importance)
     {
      case CALENDAR_IMPORTANCE_NONE:   return 0;
      case CALENDAR_IMPORTANCE_LOW:    return 1;
      case CALENDAR_IMPORTANCE_MODERATE: return 2;
      case CALENDAR_IMPORTANCE_HIGH:   return 3;
     }
   return 0;
  }

//+------------------------------------------------------------------+
//| Importance → Türkçe etiket                                        |
//+------------------------------------------------------------------+
string ImportanceLabel(int imp)
  {
   switch(imp)
     {
      case 3: return "YÜKSEK";
      case 2: return "ORTA";
      case 1: return "DÜŞÜK";
     }
   return "YOK";
  }

//+------------------------------------------------------------------+
//| JSON için özel karakterleri escape et                             |
//+------------------------------------------------------------------+
string JsonEscape(string text)
  {
   string result = text;
   StringReplace(result, "\\", "\\\\");
   StringReplace(result, "\"", "\\\"");
   StringReplace(result, "\n", "\\n");
   StringReplace(result, "\r", "\\r");
   StringReplace(result, "\t", "\\t");
   return result;
  }

//+------------------------------------------------------------------+
//| Para birimi filtresine uygun mu?                                  |
//+------------------------------------------------------------------+
bool IsCurrencyAccepted(string currency)
  {
   if(InpCurrencyFilter == "" || InpCurrencyFilter == "*")
      return true;

   string parts[];
   int count = StringSplit(InpCurrencyFilter, ',', parts);
   for(int i = 0; i < count; i++)
     {
      StringTrimLeft(parts[i]);
      StringTrimRight(parts[i]);
      if(StringCompare(parts[i], currency, false) == 0)
         return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
//| Headline oluştur: "EventName: Actual (Forecast: X, Previous: Y)"  |
//+------------------------------------------------------------------+
string BuildHeadline(string eventName, string countryCode, string actual, string forecast, string previous)
  {
   string headline = countryCode + " " + eventName;

   if(actual != "" && actual != "N/A")
      headline += ": " + actual;

   string details = "";
   if(forecast != "" && forecast != "N/A")
      details += "Beklenti: " + forecast;
   if(previous != "" && previous != "N/A")
     {
      if(details != "") details += ", ";
      details += "Önceki: " + previous;
     }

   if(details != "")
      headline += " (" + details + ")";

   return headline;
  }

//+------------------------------------------------------------------+
//| CalendarValue değerini stringe çevir                              |
//+------------------------------------------------------------------+
string ValueToString(long value)
  {
   if(value == LONG_MIN)
      return "N/A";

   // MT5 calendar değerleri 1,000,000 ile çarpılmış olabilir
   double dval = (double)value / 1000000.0;

   // Tam sayıysa .0 gösterme
   if(MathAbs(dval - MathRound(dval)) < 0.0001)
      return IntegerToString((long)MathRound(dval));

   return DoubleToString(dval, 2);
  }

//+------------------------------------------------------------------+
//| Haberleri topla ve JSON yaz                                       |
//+------------------------------------------------------------------+
int CollectAndWriteNews()
  {
   // Zaman aralığı
   datetime now = TimeCurrent();
   datetime from_time = now - InpLookbackHours * 3600;
   datetime to_time   = now + InpLookaheadHours * 3600;

   // Takvim verilerini al
   MqlCalendarValue values[];
   int total = CalendarValueHistory(values, from_time, to_time);

   if(total <= 0)
     {
      // Hata yoksa sadece veri yok demektir
      if(GetLastError() != 0)
         PrintFormat("[UstatNews] CalendarValueHistory hata: %d", GetLastError());
      return 0;
     }

   // JSON oluştur
   string json = "[\n";
   int written = 0;

   for(int i = 0; i < total && written < MAX_EVENTS; i++)
     {
      // Event detaylarını al
      MqlCalendarEvent event;
      if(!CalendarEventById(values[i].event_id, event))
         continue;

      // Ülke bilgisi al
      MqlCalendarCountry country;
      if(!CalendarCountryById(event.country_id, country))
         continue;

      // Para birimi filtresi
      if(!IsCurrencyAccepted(country.currency))
         continue;

      // Önem filtresi
      int importance = ImportanceToInt(event.importance);
      if(importance < InpMinImportance)
         continue;

      // Değerleri stringe çevir
      string actual   = ValueToString(values[i].actual_value);
      string forecast = ValueToString(values[i].forecast_value);
      string previous = ValueToString(values[i].prev_value);

      // Headline oluştur
      string headline = BuildHeadline(event.name, country.code, actual, forecast, previous);

      // Geçmiş mi gelecek mi?
      bool is_past = (values[i].time <= now);
      string status = is_past ? "RELEASED" : "UPCOMING";

      // Sürpriz hesapla (actual vs forecast)
      string surprise = "N/A";
      if(is_past && values[i].actual_value != LONG_MIN && values[i].forecast_value != LONG_MIN)
        {
         double diff = ((double)values[i].actual_value - (double)values[i].forecast_value) / 1000000.0;
         surprise = DoubleToString(diff, 2);
        }

      // JSON satırı
      if(written > 0)
         json += ",\n";

      json += "  {\n";
      json += "    \"id\": "          + IntegerToString(values[i].id) + ",\n";
      json += "    \"event_id\": "    + IntegerToString(values[i].event_id) + ",\n";
      json += "    \"headline\": \""  + JsonEscape(headline) + "\",\n";
      json += "    \"event_name\": \"" + JsonEscape(event.name) + "\",\n";
      json += "    \"time\": "        + IntegerToString((long)values[i].time) + ",\n";
      json += "    \"time_str\": \""  + TimeToString(values[i].time, TIME_DATE|TIME_MINUTES) + "\",\n";
      json += "    \"currency\": \""  + country.currency + "\",\n";
      json += "    \"country\": \""   + country.code + "\",\n";
      json += "    \"importance\": "  + IntegerToString(importance) + ",\n";
      json += "    \"importance_label\": \"" + ImportanceLabel(importance) + "\",\n";
      json += "    \"actual\": \""    + actual + "\",\n";
      json += "    \"forecast\": \""  + forecast + "\",\n";
      json += "    \"previous\": \""  + previous + "\",\n";
      json += "    \"surprise\": \""  + surprise + "\",\n";
      json += "    \"status\": \""    + status + "\"\n";
      json += "  }";

      written++;
     }

   json += "\n]";

   // Dosyaya yaz (Common Files klasörü)
   int handle = FileOpen(InpFileName, FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(handle == INVALID_HANDLE)
     {
      PrintFormat("[UstatNews] Dosya açılamadı: %s (hata: %d)", InpFileName, GetLastError());
      return -1;
     }

   FileWriteString(handle, json);
   FileClose(handle);

   return written;
  }

//+------------------------------------------------------------------+
//| Service programı ana fonksiyonu                                    |
//+------------------------------------------------------------------+
void OnStart()
  {
   PrintFormat("[UstatNews] Servis başlatıldı — aralık: %ds, geriye: %dh, ileriye: %dh",
               InpCheckIntervalSec, InpLookbackHours, InpLookaheadHours);
   PrintFormat("[UstatNews] Dosya: Common\\Files\\%s", InpFileName);
   PrintFormat("[UstatNews] Para birimleri: %s, Min önem: %d",
               InpCurrencyFilter, InpMinImportance);

   // İlk çalıştırma
   int count = CollectAndWriteNews();
   PrintFormat("[UstatNews] İlk yazım: %d haber", count);

   // Döngü
   while(!IsStopped())
     {
      Sleep(InpCheckIntervalSec * 1000);

      count = CollectAndWriteNews();

      if(count > 0)
         PrintFormat("[UstatNews] Güncelleme: %d haber yazıldı", count);
      else if(count < 0)
         PrintFormat("[UstatNews] HATA: Dosya yazılamadı");
     }

   PrintFormat("[UstatNews] Servis durduruldu");
  }
//+------------------------------------------------------------------+
