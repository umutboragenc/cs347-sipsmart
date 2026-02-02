// Clear Turbine Water Flow Sensor Driver

// Flow rate range: 1-30L/min
// Flow pulse: Frequency(Hz) = 5.0 * Q ±3% where Q = L/Min
// Each pulse = 2.25mL

// Wiring
//  - Red wire -> Power (5V)
//  - Black wire -> GND
//  - Yellow wire -> GPIO pin

// We'll change pin no. after wiring
const int FLOW_SENSOR_PIN = 0;

// Flow sensor variables
volatile unsigned long pulseCount = 0;
unsigned long lastTime = 0;
float flowRate = 0.0;          // L/min
float totalVolume = 0.0;       // Liter
float calibrationFactor = 5.0; // Pulses per L/min

const float ML_PER_PULSE = 2.25; // Approximate mL per pulse

// Calculate flow every second
const unsigned long CALC_INTERVAL = 1000;

// Callback
void IRAM_ATTR pulseCounter()
{
    pulseCount++;
}

void setup()
{
    Serial.begin(115200);
    while (!Serial)
    {
        delay(10);
    }

    Serial.println("Flow Sensor Initialized");
    Serial.println("Sensor: Clear Turbine Water Flow Sensor");
    Serial.println("Board: Seeed Studio XIAO ESP32C6");
    Serial.println("----------------------------------------");

    // Configure flow sensor pin
    pinMode(FLOW_SENSOR_PIN, INPUT_PULLUP);

    // Attach nterrupt to count pulses
    attachInterrupt(digitalPinToInterrupt(FLOW_SENSOR_PIN), pulseCounter, FALLING);

    lastTime = millis();
}
void loop()
{
    unsigned long currentTime = millis();

    // Calculate flow rate every second
    if (currentTime - lastTime >= CALC_INTERVAL)
    {
        detachInterrupt(digitalPinToInterrupt(FLOW_SENSOR_PIN));

        float frequency = pulseCount / ((currentTime - lastTime) / 1000.0);
        flowRate = frequency / calibrationFactor;

        float volumeThisSecond = (pulseCount * ML_PER_PULSE) / 1000.0; // Convert mL to L
        totalVolume += volumeThisSecond;

        // Print results
        Serial.println("----------------------------------------");
        Serial.print("Pulses: ");
        Serial.println(pulseCount);
        Serial.print("Flow Rate: ");
        Serial.print(flowRate, 2);
        Serial.println(" L/min");
        Serial.print("Volume (this interval): ");
        Serial.print(volumeThisSecond * 1000, 2);
        Serial.println(" mL");
        Serial.print("Total Volume: ");
        Serial.print(totalVolume, 3);
        Serial.println(" L");
        Serial.println();

        // Reset pulse counter
        pulseCount = 0;
        lastTime = currentTime;

        attachInterrupt(digitalPinToInterrupt(FLOW_SENSOR_PIN), pulseCounter, FALLING);
    }

    delay(10);
}

// Getters
float getFlowRate()
{
    return flowRate;
}

float getTotalVolume()
{
    return totalVolume;
}

// Function to reset total volume
void resetTotalVolume()
{
    totalVolume = 0.0;
    Serial.println("Total volume reset to 0");
}

void setCalibrationFactor(float factor)
{
    calibrationFactor = factor;
    Serial.print("Calibration factor set to: ");
    Serial.println(calibrationFactor);
}
