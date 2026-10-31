# AIL: Aziende Industriali di Lugano - Home Assistant Integration

This integration allows you to monitor your energy consumption data from Aziende Industriali di Lugano (AIL) in Home Assistant.

## Features

- Fetch energy consumption data from AIL EnergyBuddy
- Separate day and night consumption tracking
- Energy dashboard integration
- Cost calculation based on peak and off-peak rates
- Estimated weekly consumption by Energy Buddy appliance category

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
- Sensor for estimated total weekly consumption
- One estimated weekly consumption sensor per Energy Buddy appliance category
- Statistics sensor for daily consumption
- Statistics sensor for daily cost
- Statistics sensor for nightly consumption
- Statistics sensor for nightly cost
- Statistics sensor for total consumption
- Statistics sensor for total cost

You can add the cumulative consumption statistics to Home Assistant's Energy dashboard.

Category sensors are provider-generated estimates, not additional meter readings. They
use the `measurement` state class and are intentionally kept separate from the
authoritative cumulative totals used by the Energy dashboard.

## Local development

1. Open this repository in VS Code with Docker running and the Dev Containers extension installed.
2. Run **Dev Containers: Reopen in Container**. Setup installs Home Assistant and the test dependencies.
3. In the container terminal, run `scripts/run` and open the forwarded port at [http://localhost:8123](http://localhost:8123).
4. Complete Home Assistant onboarding with a new local account, then add **AIL: Aziende Industriali di Lugano** under **Settings > Devices & services** to test the AIL login.

The development instance stores its configuration, accounts, database and logs in
`.devcontainer/ha-config/`, which is ignored by Git and separate from `config/`.
The AIL integration is linked to the working copy; stop Home Assistant with Ctrl+C
and run `scripts/run` again after changing Python files. AIL debug logging is enabled
in the development configuration; logs appear in the terminal and in
`.devcontainer/ha-config/home-assistant.log`.

Run `python -m pytest -q` inside the container for automated tests. The Home Assistant
version comes from the test dependency constraints in `requirements_test.txt`.
Additional frontend runtime dependencies for Home Assistant 2026.2.3 are listed in
`.devcontainer/requirements.txt`; keep them aligned when upgrading Home Assistant.
Setup also verifies the service imports used by the UI after login.
To reset the instance, stop it and delete only `.devcontainer/ha-config/`.

Development environment reference: [Home Assistant contributor documentation](https://contributors.home-assistant.io/core/development/environment/).

## Support

For issues, feature requests, or contributions, please use the [GitHub Issues](https://github.com/lukefx/ail-ha/issues) page.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
