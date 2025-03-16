# AIL: Aziende Industriali di Lugano - Home Assistant Integration

This integration allows you to monitor your energy consumption data from Aziende Industriali di Lugano (AIL) in Home Assistant.

## Features

- Fetch energy consumption data from AIL EnergyBuddy
- Separate day and night consumption tracking
- Energy dashboard integration
- Cost calculation based on peak and off-peak rates

## Installation

### HACS Installation (Recommended)

1. Make sure you have [HACS](https://hacs.xyz/) installed in your Home Assistant instance.
2. Click on HACS in the sidebar.
3. Click on "Integrations".
4. Click the three dots in the top right corner and select "Custom repositories".
5. Enter the URL of this repository: `https://github.com/lukefx/ail-ha`
6. Select "Integration" as the category.
7. Click "ADD".
8. Search for "AIL" in the integrations tab.
9. Click on "AIL: Aziende Industriali di Lugano".
10. Click "DOWNLOAD" in the bottom right corner.
11. Restart Home Assistant.

### Manual Installation

1. Download the latest release from the [releases page](https://github.com/lukefx/ail-ha/releases).
2. Extract the contents and copy the `custom_components/ail` directory to your Home Assistant's `custom_components` directory.
3. Restart Home Assistant.

## Configuration
 
1. Go to Home Assistant's Settings > Devices & Services.
2. Click on the "+ ADD INTEGRATION" button in the bottom right corner.
3. Search for "AIL" and select "AIL: Aziende Industriali di Lugano".
4. Enter your AIL EnergyBuddy credentials (email and password).
5. Configure your electricity tariff settings (optional).

## Usage

After setup, the integration will create the following entities:

- Sensor for day consumption (Last parsed hour)
- Sensor for night consumption (Last parsed hour)
- Sensor for total consumption
- Sensor for current price of energy consumption
- Statistics sensor for daily consumption
- Statistics sensor for daily cost
- Statistics sensor for nightly consumption
- Statistics sensor for nightly cost
- Statistics sensor for total consumption
- Statistics sensor for total cost

You can add these to the Energy dashboard in Home Assistant to visualize your energy usage.

## Support

For issues, feature requests, or contributions, please use the [GitHub Issues](https://github.com/lukefx/ail-ha/issues) page.

## License

This project is licensed under the MIT License - see the LICENSE file for details.