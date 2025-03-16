# AIL: Aziende Industriali di Lugano - Home Assistant Integration

This integration allows you to monitor your energy consumption data from Aziende Industriali di Lugano (AIL) in Home Assistant.

## Features

- Fetch energy consumption data from AIL EnergyBuddy
- Separate day and night consumption tracking
- Energy dashboard integration
- Cost calculation based on peak and off-peak rates

## Configuration
 
1. Go to Home Assistant's Settings > Devices & Services.
2. Click on the "+ ADD INTEGRATION" button in the bottom right corner.
3. Search for "AIL" and select "AIL: Aziende Industriali di Lugano".
4. Enter your AIL EnergyBuddy credentials (email and password).
5. Configure your electricity tariff settings (optional).

## Usage

After setup, the integration will create the following entities:

- Sensor for day consumption
- Sensor for night consumption 
- Sensor for total consumption
- Sensor for current price of energy consumption

You can add these to the Energy dashboard in Home Assistant to visualize your energy usage.
