import asyncio
from bleak import BleakScanner, BleakClient

# Nordic UART Service (NUS) UUIDs
NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
NUS_TX_UUID      = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # Notify: ESP32 -> PC
# NUS_RX_UUID    = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # Write:  PC -> ESP32 (optional)

DEVICE_NAME = "XIAO_Flow"

def handle_notify(_: int, data: bytearray):
    # If you send ASCII text (recommended), decode it:
    try:
        print(data.decode("utf-8", errors="ignore").strip())
    except Exception:
        print(list(data))

async def main():
    print("Scanning for device...")
    devices = await BleakScanner.discover(timeout=8.0)

    target = None
    for d in devices:
        if d.name == DEVICE_NAME:
            target = d
            break

    if not target:
        print(f"Could not find {DEVICE_NAME}. Found:")
        for d in devices:
            print(d.name, d.address)
        return

    print(f"Connecting to {target.name} ({target.address})...")
    async with BleakClient(target.address) as client:
        # Subscribe to notifications (same as the "down arrow" you tapped in nRF Connect)
        await client.start_notify(NUS_TX_UUID, handle_notify)
        print("Subscribed. Streaming... Ctrl+C to stop.")
        while True:
            await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
