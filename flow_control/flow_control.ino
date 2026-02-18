// Clear Turbine Water Flow Sensor Driver + BLE Notify (ESP32 Arduino core BLEDevice.h)
// Board: Seeed Studio XIAO ESP32-C6
//
// Flow rate range: 1–30 L/min
// Flow pulse: Frequency(Hz) = 5.0 * Q ±3% where Q = L/min
// Each pulse ≈ 2.25 mL (approx; calibrate)
//
// Wiring
//  - Red   -> 5V
//  - Black -> GND
//  - Yellow-> GPIO via voltage divider to 3.3V (IMPORTANT)
//
// Notes:
//  - Because you are using a voltage divider, use INPUT (NOT INPUT_PULLUP).
//  - ESP32-C6 uses BLE (Bluetooth Low Energy), not Bluetooth Classic SPP.
//  - Use a BLE app like "nRF Connect" to view notifications.

#include <Arduino.h>

// ESP32 BLE (comes with ESP32 Arduino core)
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// -------------------- FLOW SENSOR CONFIG --------------------
const int FLOW_SENSOR_PIN = 2;

// Flow sensor variables
volatile unsigned long pulseCount = 0;
unsigned long lastTime = 0;

float flowRate = 0.0;          // L/min
float totalVolume = 0.0;       // Liter
float calibrationFactor = 5.0; // Frequency(Hz) = 5.0 * Q (L/min)

const float ML_PER_PULSE = 2.25;          // Approximate mL per pulse
const unsigned long CALC_INTERVAL = 100; // Calculate every second

// -------------------- BLE CONFIG --------------------
#define BLE_DEVICE_NAME "XIAO_Flow"

// Nordic UART-like UUIDs (commonly used; works fine for custom payloads)
static const char *SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
static const char *CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"; // notify/read

BLEServer *pServer = nullptr;
BLECharacteristic *pCharacteristic = nullptr;
bool deviceConnected = false;

class MyServerCallbacks : public BLEServerCallbacks
{
  void onConnect(BLEServer *server) override
  {
    deviceConnected = true;
  }
  void onDisconnect(BLEServer *server) override
  {
    deviceConnected = false;
    server->startAdvertising(); // allow reconnect
  }
};

// Callback for flow pulses
void IRAM_ATTR pulseCounter()
{
  pulseCount++;
}

// BLE init
void setupBLE()
{
  BLEDevice::init(BLE_DEVICE_NAME);

  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());

  BLEService *pService = pServer->createService(SERVICE_UUID);

  pCharacteristic = pService->createCharacteristic(
      CHAR_UUID,
      BLECharacteristic::PROPERTY_READ |
          BLECharacteristic::PROPERTY_NOTIFY);

  // CCCD descriptor so apps can enable notifications
  pCharacteristic->addDescriptor(new BLE2902());

  // Optional initial value (header)
  pCharacteristic->setValue("pulses,frequency_hz,flow_l_min,vol_ml_interval,total_l");

  pService->start();

  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(true);
  pAdvertising->start();
}

void setup()
{
  Serial.begin(115200);
  delay(300);

  Serial.println("Flow Sensor Initialized (BLE)");
  Serial.println("Sensor: Clear Turbine Water Flow Sensor");
  Serial.println("Board: Seeed Studio XIAO ESP32C6");
  Serial.println("----------------------------------------");

  // Configure flow sensor pin
  // With a voltage divider to 3.3V, do NOT use INPUT_PULLUP.
  pinMode(FLOW_SENSOR_PIN, INPUT);

  // Attach interrupt to count pulses
  attachInterrupt(digitalPinToInterrupt(FLOW_SENSOR_PIN), pulseCounter, FALLING);

  // Start BLE
  setupBLE();

  Serial.print("BLE Device Name: ");
  Serial.println(BLE_DEVICE_NAME);
  Serial.println("Open nRF Connect -> connect -> enable Notify on characteristic.");
  Serial.println("----------------------------------------");

  lastTime = millis();
}

void loop()
{
  unsigned long currentTime = millis();

  // Calculate flow rate every second
  if (currentTime - lastTime >= CALC_INTERVAL)
  {

    // Snapshot pulses safely (no detachInterrupt needed)
    noInterrupts();
    unsigned long pulses = pulseCount;
    pulseCount = 0;
    interrupts();

    // Calculate frequency (Hz) from pulse count
    float elapsedSeconds = (currentTime - lastTime) / 1000.0f;
    float frequency = (elapsedSeconds > 0) ? (pulses / elapsedSeconds) : 0.0f;

    // Flow rate from formula: Frequency(Hz) = 5.0 * Q (L/min)
    flowRate = frequency / calibrationFactor;

    // Calculate volume for this interval
    float volumeThisInterval_L = (pulses * ML_PER_PULSE) / 1000.0f;
    float volumeThisInterval_mL = volumeThisInterval_L * 1000.0f;
    totalVolume += volumeThisInterval_L;

    // Print results to Serial
    Serial.println("----------------------------------------");
    Serial.print("Pulses: ");
    Serial.println(pulses);
    Serial.print("Frequency: ");
    Serial.print(frequency, 2);
    Serial.println(" Hz");
    Serial.print("Flow Rate: ");
    Serial.print(flowRate, 3);
    Serial.println(" L/min");
    Serial.print("Volume (this interval): ");
    Serial.print(volumeThisInterval_mL, 2);
    Serial.println(" mL");
    Serial.print("Total Volume: ");
    Serial.print(totalVolume, 4);
    Serial.println(" L");
    Serial.println();

    // Send BLE notification (CSV payload)
    if (deviceConnected && pCharacteristic)
    {
      char payload[128];
      // pulses,frequency_hz,flow_l_min,vol_ml_interval,total_l
      snprintf(payload, sizeof(payload),
               "%lu,%.2f,%.3f,%.2f,%.4f",
               pulses,
               frequency,
               flowRate,
               volumeThisInterval_mL,
               totalVolume);

      pCharacteristic->setValue((uint8_t *)payload, strlen(payload));
      pCharacteristic->notify();
    }

    lastTime = currentTime;
  }

  delay(50);
}
