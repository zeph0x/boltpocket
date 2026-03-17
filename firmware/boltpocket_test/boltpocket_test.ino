/*
 * M5Paper S3 — minimal display test
 * If this doesn't show anything, the display driver config is wrong.
 */

#include <M5Unified.h>

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n--- M5Paper S3 Test ---");

  auto cfg = M5.config();
  M5.begin(cfg);

  Serial.printf("Display width: %d, height: %d\n", M5.Display.width(), M5.Display.height());
  Serial.printf("Board: %d\n", M5.getBoard());

  M5.Display.setEpdMode(epd_mode_t::epd_quality);
  M5.Display.fillScreen(TFT_WHITE);
  M5.Display.setTextColor(TFT_BLACK, TFT_WHITE);
  M5.Display.setTextSize(3);
  M5.Display.setCursor(30, 30);
  M5.Display.println("BoltPocket");
  M5.Display.setTextSize(2);
  M5.Display.println("M5Paper S3 test");
  M5.Display.printf("Display: %dx%d\n", M5.Display.width(), M5.Display.height());
  M5.Display.println("If you see this, display works!");

  Serial.println("Display drawn. Check the screen.");
}

void loop() {
  delay(10000);
}
