# Config files for running timDIMM web GUI

- **timdimm.service** -- This configures the server to run via `systemctl`. Place this file in `/etc/systemd/system/` and then do:
```bash
sudo systemctl daemon-reload
sudo systemctl restart timdimm.service
```
- **timdimm.conf** -- This configures `apache2` to proxy route traffic from the default URL to `timdimm.service`. Place this file in
`/etc/apache2/sites-available` and then do:
```bash
sudo a2enmod proxy_http
sudo a2ensite timdimm.conf
sudo systemctl restart apache2
```

## Adafruit SHT45 logger

Link the logger, rotation service, and timer into the systemd configuration:

```bash
sudo ln -s /home/timdimm/timdimm_tng/config/adafruit-sht45.service /etc/systemd/system/adafruit-sht45.service
sudo ln -s /home/timdimm/timdimm_tng/config/adafruit-sht45-rotate.service /etc/systemd/system/adafruit-sht45-rotate.service
sudo ln -s /home/timdimm/timdimm_tng/config/adafruit-sht45-rotate.timer /etc/systemd/system/adafruit-sht45-rotate.timer
sudo systemctl daemon-reload
sudo systemctl enable --now adafruit-sht45.service adafruit-sht45-rotate.timer
```

The timer stops the logger daily at 10:00 UTC (local noon), moves `~/adafruit.csv` to
`~/adafruit-YYYY-MM-DD.csv`, compresses it with gzip, and restarts the logger with a fresh CSV file. Check the timer and rotation logs with:

```bash
systemctl list-timers adafruit-sht45-rotate.timer
journalctl -u adafruit-sht45-rotate.service
```
