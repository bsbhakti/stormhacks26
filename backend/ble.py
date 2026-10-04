import asyncio
from bleak import BleakScanner



async def main():
    stop_event = asyncio.Event()

    # TODO: add something that calls stop_event.set()

    def detection_callback(device, advertisement_data):
        print(
            device.name,
            device.address,
            advertisement_data.rssi
        )

    async with BleakScanner(detection_callback=detection_callback) as _:
        ...
        # Important! Wait for an event to trigger stop, otherwise scanner
        # will stop immediately.
        await stop_event.wait()

    # scanner stops when block exits
asyncio.run(main())