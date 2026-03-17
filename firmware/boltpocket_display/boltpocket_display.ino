/*
 * BoltPocket Balance Display — M5Stack Paper S3
 *
 * Shows wallet balances + BTC/CHF price on e-ink display.
 * Fetches from BoltPocket API, then deep sleeps to save power.
 *
 * Setup:
 *   1. Install Arduino IDE + ESP32 board support
 *   2. Install libraries: M5Unified, M5GFX, ArduinoJson
 *   3. Edit config below (WiFi + API keys)
 *   4. Select board: "M5Paper S3" or "ESP32S3 Dev Module"
 *   5. Upload
 *
 * Display: 540 x 960 pixels, 16 grayscale levels
 */

#include <M5Unified.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ============================================================
// CONFIG — edit these
// ============================================================

const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASS     = "YOUR_WIFI_PASSWORD";

// BoltPocket server URL (no trailing slash)
const char* SERVER_URL    = "https://your-boltpocket-server.com";

// API endpoint is built from SERVER_URL automatically
// Override if your server uses a different path
// const char* API_URL    = "https://custom-url.com/api/v1/balance/";

// API keys (SHA256 of access key) — from CSV api_key column
// Add one per wallet to display
const char* API_KEYS[] = {
  "key1_sha256_hash_here",
  "key2_sha256_hash_here",
  // "key3_sha256_hash_here",
};
const int NUM_WALLETS = 2;  // match the number of keys above

// Wallet display names (same order as keys)
const char* WALLET_NAMES[] = {
  "Leo",
  "Mia",
  // "Oma",
};

// Weather location (city name or coordinates)
const char* WEATHER_LOCATION = "Zurich";

// How often to refresh (minutes)
const int REFRESH_INTERVAL_MIN = 60;

// Set to true during development to keep USB alive (no deep sleep)
const bool DEV_MODE = true;

// ============================================================
// DISPLAY LAYOUT
// ============================================================

// M5Paper S3: 540 x 960, portrait orientation
const int SCREEN_W = 540;
const int SCREEN_H = 960;

// Colors — use M5GFX built-in constants for e-ink compatibility
#define CLR_BLACK TFT_BLACK
#define CLR_DARK TFT_DARKGREY
#define CLR_MID TFT_DARKGREY
#define CLR_LIGHT TFT_LIGHTGREY
#define CLR_WHITE TFT_WHITE

// ============================================================
// DATA
// ============================================================

struct WalletData {
  String name;
  String ln_address;
  int balance_sats;
  String value_chf;
  bool valid;
};

WalletData wallets[10];  // max 10 wallets
String btc_price_chf = "—";
int wallet_count = 0;

struct WeatherData {
  String temp;
  String feelsLike;
  String desc;
  String humidity;
  String windSpeed;
  int code;
  bool valid;
};

WeatherData weather = { "", "", "", "", "", 0, false };

// ============================================================
// FUNCTIONS
// ============================================================

bool connectWiFi() {
  Serial.printf("Connecting to %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("Connected! IP: %s\n", WiFi.localIP().toString().c_str());
    return true;
  }

  Serial.println("WiFi connection failed!");
  return false;
}

bool fetchBalances() {
  // Build URL with all keys
  String url = String(SERVER_URL) + "/api/v1/balance/?";
  for (int i = 0; i < NUM_WALLETS; i++) {
    if (i > 0) url += "&";
    url += "key=" + String(API_KEYS[i]);
  }

  HTTPClient http;
  http.begin(url);
  http.setTimeout(15000);

  int httpCode = http.GET();
  if (httpCode != 200) {
    Serial.printf("HTTP error: %d\n", httpCode);
    http.end();
    return false;
  }

  String payload = http.getString();
  http.end();

  // Parse JSON
  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, payload);
  if (error) {
    Serial.printf("JSON parse error: %s\n", error.c_str());
    return false;
  }

  // Get BTC price
  if (doc["prices"]["CHF"]) {
    btc_price_chf = doc["prices"]["CHF"].as<String>();
    // Trim to integer
    int dot = btc_price_chf.indexOf('.');
    if (dot > 0) btc_price_chf = btc_price_chf.substring(0, dot);
  }

  // Single wallet response (flat)
  if (doc["balance_sats"]) {
    wallet_count = 1;
    wallets[0].name = WALLET_NAMES[0];
    wallets[0].balance_sats = doc["balance_sats"];
    wallets[0].value_chf = doc["value_chf"].as<String>();
    wallets[0].ln_address = doc["ln_address"].as<String>();
    wallets[0].valid = true;
    return true;
  }

  // Multi wallet response
  JsonArray arr = doc["wallets"].as<JsonArray>();
  wallet_count = 0;
  for (JsonObject w : arr) {
    if (wallet_count >= NUM_WALLETS) break;
    wallets[wallet_count].name = WALLET_NAMES[wallet_count];
    wallets[wallet_count].balance_sats = w["balance_sats"];
    wallets[wallet_count].value_chf = w["value_chf"].as<String>();
    wallets[wallet_count].ln_address = w["ln_address"].as<String>();
    wallets[wallet_count].valid = true;
    wallet_count++;
  }

  return wallet_count > 0;
}

bool fetchWeather() {
  HTTPClient http;
  String weatherUrl = "https://wttr.in/" + String(WEATHER_LOCATION) + "?format=j1";
  http.begin(weatherUrl);
  http.setTimeout(10000);

  int httpCode = http.GET();
  if (httpCode != 200) {
    Serial.printf("Weather HTTP error: %d\n", httpCode);
    http.end();
    return false;
  }

  String payload = http.getString();
  http.end();

  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, payload);
  if (error) {
    Serial.printf("Weather JSON error: %s\n", error.c_str());
    return false;
  }

  JsonObject cur = doc["current_condition"][0];
  weather.temp = cur["temp_C"].as<String>();
  weather.feelsLike = cur["FeelsLikeC"].as<String>();
  weather.desc = cur["weatherDesc"][0]["value"].as<String>();
  weather.humidity = cur["humidity"].as<String>();
  weather.windSpeed = cur["windspeedKmph"].as<String>();
  weather.code = cur["weatherCode"].as<int>();
  weather.valid = true;

  Serial.printf("Weather: %s°C, %s\n", weather.temp.c_str(), weather.desc.c_str());
  return true;
}

// Simple weather icon using primitives
void drawWeatherIcon(int cx, int cy, int size, int code) {
  auto &display = M5.Display;
  int r = size / 2;

  if (code == 113) {
    // Clear/Sunny — sun with rays
    display.fillCircle(cx, cy, r/2, CLR_BLACK);
    for (int a = 0; a < 360; a += 45) {
      float rad = a * 3.14159 / 180.0;
      int x1 = cx + (int)(r*0.6 * cos(rad));
      int y1 = cy + (int)(r*0.6 * sin(rad));
      int x2 = cx + (int)(r * cos(rad));
      int y2 = cy + (int)(r * sin(rad));
      display.drawLine(x1, y1, x2, y2, CLR_BLACK);
    }
  } else if (code == 116 || code == 119) {
    // Partly cloudy / Cloudy — cloud
    display.fillCircle(cx - r/4, cy, r/3, CLR_BLACK);
    display.fillCircle(cx + r/4, cy - r/6, r/3, CLR_BLACK);
    display.fillCircle(cx + r/2, cy + r/6, r/4, CLR_BLACK);
    display.fillRoundRect(cx - r/2, cy, r, r/3, 4, CLR_BLACK);
  } else if (code >= 176 && code <= 399) {
    // Rain/snow/sleet — cloud + drops
    display.fillCircle(cx - r/4, cy - r/4, r/4, CLR_BLACK);
    display.fillCircle(cx + r/4, cy - r/3, r/4, CLR_BLACK);
    display.fillRoundRect(cx - r/2, cy - r/4, r, r/4, 4, CLR_BLACK);
    // Drops
    for (int i = -1; i <= 1; i++) {
      display.fillCircle(cx + i * r/3, cy + r/3, 2, CLR_BLACK);
      display.drawLine(cx + i * r/3, cy + r/6, cx + i * r/3, cy + r/3, CLR_BLACK);
    }
  } else {
    // Fallback — just show a cloud
    display.fillCircle(cx - r/4, cy, r/3, CLR_DARK);
    display.fillCircle(cx + r/4, cy - r/6, r/3, CLR_DARK);
    display.fillRoundRect(cx - r/2, cy, r, r/3, 4, CLR_DARK);
  }
}

String formatSats(int sats) {
  // Add thousand separators: 12345 -> "12'345"
  String s = String(sats);
  String result = "";
  int len = s.length();
  for (int i = 0; i < len; i++) {
    if (i > 0 && (len - i) % 3 == 0) result += "'";
    result += s[i];
  }
  return result;
}

void drawSmiley(int cx, int cy, int r) {
  auto &display = M5.Display;
  display.drawCircle(cx, cy, r, CLR_BLACK);
  display.drawCircle(cx, cy, r-1, CLR_BLACK);
  display.fillCircle(cx - r*3/10, cy - r*2/10, r/8, CLR_BLACK);
  display.fillCircle(cx + r*3/10, cy - r*2/10, r/8, CLR_BLACK);
  for (int a = 20; a <= 160; a += 2) {
    float rad = a * 3.14159 / 180.0;
    int sx = cx + (int)(r * 0.45 * cos(rad));
    int sy = cy + (int)(r * 0.45 * sin(rad));
    display.drawPixel(sx, sy, CLR_BLACK);
    display.drawPixel(sx, sy+1, CLR_BLACK);
  }
}

void drawHeart(int cx, int cy, int size) {
  auto &display = M5.Display;
  int s = size;
  // Two filled circles for the top bumps
  display.fillCircle(cx - s/4, cy - s/8, s/4, CLR_BLACK);
  display.fillCircle(cx + s/4, cy - s/8, s/4, CLR_BLACK);
  // Triangle for the bottom point
  display.fillTriangle(
    cx - s/2, cy,
    cx + s/2, cy,
    cx,       cy + s/2,
    CLR_BLACK
  );
}

// Icons per wallet index — add more as needed
void drawWalletIcon(int index, int cx, int cy, int size) {
  switch (index) {
    case 0: drawSmiley(cx, cy, size); break;
    case 1: drawHeart(cx, cy, size); break;
    default: drawSmiley(cx, cy, size); break;
  }
}

void drawWalletCard(int y, WalletData &w, int cardHeight, int index) {
  auto &display = M5.Display;

  // Card background (subtle rounded rect)
  display.fillRoundRect(20, y, SCREEN_W - 40, cardHeight, 12, CLR_LIGHT);
  display.fillRoundRect(24, y + 4, SCREEN_W - 48, cardHeight - 8, 10, CLR_WHITE);

  // Icon
  drawWalletIcon(index, SCREEN_W - 70, y + cardHeight / 2, 30);

  // Name (big, friendly)
  display.setFont(&fonts::FreeSansBold24pt7b);
  display.setTextColor(CLR_BLACK, CLR_WHITE);
  display.drawString(w.name, 45, y + 20);

  // Sats balance (the star of the show)
  display.setFont(&fonts::FreeSansBold24pt7b);
  display.setTextColor(CLR_BLACK, CLR_WHITE);
  String satsStr = formatSats(w.balance_sats);
  display.drawString(satsStr + " sats", 45, y + 80);

  // CHF value
  display.setFont(&fonts::FreeSans18pt7b);
  display.setTextColor(CLR_DARK, CLR_WHITE);
  display.drawString("= CHF " + w.value_chf, 45, y + 130);
}

void drawDisplay() {
  auto &display = M5.Display;
  display.setEpdMode(epd_mode_t::epd_quality);
  display.fillScreen(CLR_WHITE);

  // Calculate card layout
  int topMargin = 30;
  int bottomReserved = 80;  // for footer
  int spacing = 20;
  int availableHeight = SCREEN_H - topMargin - bottomReserved;
  int cardHeight = (availableHeight - spacing * (wallet_count - 1)) / wallet_count;
  if (cardHeight > 200) cardHeight = 200;  // cap height

  // Draw wallet cards
  int y = topMargin;
  for (int i = 0; i < wallet_count; i++) {
    if (!wallets[i].valid) continue;
    drawWalletCard(y, wallets[i], cardHeight, i);
    y += cardHeight + spacing;
  }

  // Weather section
  if (weather.valid) {
    y += spacing;
    display.fillRoundRect(20, y, SCREEN_W - 40, 80, 12, CLR_LIGHT);
    display.fillRoundRect(24, y + 4, SCREEN_W - 48, 72, 10, CLR_WHITE);

    // Weather icon
    drawWeatherIcon(65, y + 40, 40, weather.code);

    // Temp + description
    display.setFont(&fonts::FreeSansBold18pt7b);
    display.setTextColor(CLR_BLACK, CLR_WHITE);
    display.drawString(weather.temp + "C", 100, y + 12);

    display.setFont(&fonts::FreeSans12pt7b);
    display.setTextColor(CLR_DARK, CLR_WHITE);
    display.drawString(weather.desc, 100, y + 48);

    // Feels like on the right
    display.setFont(&fonts::FreeSans9pt7b);
    display.setTextColor(CLR_MID, CLR_WHITE);
    display.drawString("Feels " + weather.feelsLike + "C", SCREEN_W - 140, y + 20);
    display.drawString(weather.humidity + "% hum", SCREEN_W - 140, y + 45);
  }

  // Footer: BTC price + update time (small, subtle)
  int footerY = SCREEN_H - 55;
  display.drawFastHLine(30, footerY, SCREEN_W - 60, CLR_LIGHT);
  footerY += 15;

  display.setFont(&fonts::FreeSans9pt7b);
  display.setTextColor(CLR_MID, CLR_WHITE);
  display.drawString("1 BTC = CHF " + btc_price_chf, 30, footerY);

  struct tm timeinfo;
  if (getLocalTime(&timeinfo)) {
    char timeStr[32];
    strftime(timeStr, sizeof(timeStr), "%H:%M", &timeinfo);
    display.drawString(timeStr, SCREEN_W - 80, footerY);
  }

  // Flush to e-ink
  display.display();
  display.waitDisplay();
}

void drawError(const char* msg) {
  auto &display = M5.Display;
  display.setEpdMode(epd_mode_t::epd_quality);
  display.fillScreen(CLR_WHITE);
  display.setTextColor(CLR_BLACK, CLR_WHITE);
  display.setFont(&fonts::FreeSansBold18pt7b);
  display.drawString("BoltPocket", 30, 30);
  display.setFont(&fonts::FreeSans12pt7b);
  display.setTextColor(CLR_DARK, CLR_WHITE);
  display.drawString(msg, 30, 100);
  display.drawString("Retrying in " + String(REFRESH_INTERVAL_MIN) + " min...", 30, 140);

  // Flush to e-ink
  display.display();
  display.waitDisplay();
}

// ============================================================
// MAIN
// ============================================================

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);

  Serial.begin(115200);
  Serial.println("\n--- BoltPocket Display ---");

  // Set timezone (CET)
  configTzTime("CET-1CEST,M3.5.0,M10.5.0/3", "pool.ntp.org");

  if (!connectWiFi()) {
    drawError("WiFi connection failed");
    goToSleep();
    return;
  }

  // Sync time
  delay(1000);

  if (fetchBalances()) {
    Serial.printf("Fetched %d wallets, BTC/CHF: %s\n", wallet_count, btc_price_chf.c_str());
    fetchWeather();  // non-critical, display works without it
    drawDisplay();
  } else {
    Serial.println("Failed to fetch balances");
    drawError("Could not fetch balances");
  }

  WiFi.disconnect(true);
  goToSleep();
}

void refreshBalances() {
  Serial.println("Refreshing...");
  if (connectWiFi()) {
    delay(500);
    if (fetchBalances()) {
      Serial.printf("Fetched %d wallets, BTC/CHF: %s\n", wallet_count, btc_price_chf.c_str());
      fetchWeather();
      drawDisplay();
    } else {
      drawError("Could not fetch balances");
    }
    WiFi.disconnect(true);
  } else {
    drawError("WiFi connection failed");
  }
}

void goToSleep() {
  if (DEV_MODE) {
    Serial.println("DEV_MODE: press button to refresh, or wait for auto-refresh...");
    unsigned long start = millis();
    unsigned long interval = (uint32_t)REFRESH_INTERVAL_MIN * 60 * 1000UL;
    while (millis() - start < interval) {
      M5.update();
      if (M5.BtnA.wasPressed() || M5.BtnB.wasPressed() || M5.BtnC.wasPressed()) {
        Serial.println("Button pressed — refreshing!");
        refreshBalances();
        start = millis();  // reset timer
      }
      delay(100);
    }
    ESP.restart();
    return;
  }

  Serial.printf("Sleeping for %d minutes (press power to wake)...\n", REFRESH_INTERVAL_MIN);
  // Timer wake
  esp_sleep_enable_timer_wakeup((uint64_t)REFRESH_INTERVAL_MIN * 60 * 1000000ULL);
  // Power button wake — on M5Paper S3, power button press triggers reset from deep sleep
  esp_deep_sleep_start();
}

void loop() {
  // Never reaches here in deep sleep mode
  // In DEV_MODE, loop is not used (goToSleep handles button polling)
}
