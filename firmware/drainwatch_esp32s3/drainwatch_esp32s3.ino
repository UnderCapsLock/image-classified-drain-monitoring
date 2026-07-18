
#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <base64.h>

// you can change this
const char* WIFI_SSID     = "yourssid";
const char* WIFI_PASSWORD = "yourpassword";
const char* SERVER_IP     = "10.94.179.50";   // do ipconfig, take ipv4 address
const int   SERVER_PORT   = 5000;
const char* NODE_NAME     = "cameranode-1";
const int   CAPTURE_EVERY_MS = 3000; // change for speed, minimal returns past 3 seconds

// pin map
#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     15
#define SIOD_GPIO_NUM      4
#define SIOC_GPIO_NUM      5
#define Y9_GPIO_NUM       16
#define Y8_GPIO_NUM       17
#define Y7_GPIO_NUM       18
#define Y6_GPIO_NUM       12
#define Y5_GPIO_NUM       10
#define Y4_GPIO_NUM        8
#define Y3_GPIO_NUM        9
#define Y2_GPIO_NUM       11
#define VSYNC_GPIO_NUM     6
#define HREF_GPIO_NUM      7
#define PCLK_GPIO_NUM     13

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = FRAMESIZE_QVGA;
  config.jpeg_quality = 12;
  config.fb_count     = 2;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("Camera init failed");
    return false;
  }

  sensor_t* s = esp_camera_sensor_get();
  s->set_brightness(s, 1);
  s->set_contrast(s, 1);
  s->set_whitebal(s, 1);
  s->set_awb_gain(s, 1);
  s->set_exposure_ctrl(s, 1);
  s->set_aec2(s, 1);
  Serial.println("Camera OK");
  return true;
}

bool connectWifi() {
  Serial.printf("Connecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);   
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500); Serial.print("."); attempts++;
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nWi-Fi FAILED"); return false;
  }
  Serial.printf("\nConnected — IP: %s\n", WiFi.localIP().toString().c_str());
  return true;
}

bool ensureWifiConnected() {
  if (WiFi.status() == WL_CONNECTED) return true;

  Serial.println("Wi-Fi down — attempting reconnect...");
  WiFi.disconnect();
  delay(500);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 15) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nReconnected — IP: %s\n", WiFi.localIP().toString().c_str());
    return true;
  }
  Serial.println("\nReconnect failed, will retry next cycle");
  return false;
}

void captureAndSend() {
  if (!ensureWifiConnected()) {
    Serial.println("Skipping this capture — no Wi-Fi");
    return;
  }

  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { Serial.println("Capture failed"); return; }
  Serial.printf("Captured %d bytes\n", fb->len);

  String encoded = base64::encode(fb->buf, fb->len);
  esp_camera_fb_return(fb);

  String json = "{";
  json += "\"node\":\"" + String(NODE_NAME) + "\",";
  json += "\"image\":\"" + encoded + "\"";
  json += "}";

  String url = "http://" + String(SERVER_IP) + ":" + String(SERVER_PORT) + "/upload";

  int code = -1;
  int retries = 0;
  while (code != 200 && retries < 3) {
    HTTPClient http;
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(5000);
    code = http.POST(json);
    if (code == 200) {
      Serial.printf("Sent OK — server: %s\n", http.getString().c_str());
    } else {
      Serial.printf("HTTP error: %d (attempt %d/3)\n", code, retries + 1);
      retries++;
      if (retries < 3) delay(500);
    }
    http.end();
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("\nStarting...");
  if (!initCamera()) { delay(5000); ESP.restart(); }
  if (!connectWifi()) { delay(5000); ESP.restart(); }
  Serial.printf("Node: %s | Server: %s:%d\n", NODE_NAME, SERVER_IP, SERVER_PORT);
}

void loop() {
  captureAndSend();
  delay(CAPTURE_EVERY_MS);
}
