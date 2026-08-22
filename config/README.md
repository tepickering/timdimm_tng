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

## Weather CSV rotation

`status.py` appends SALT and SAAO IO readings to `~/salt_wx.csv` and `~/saao_io.csv` as the roof
interface polls them. Link the rotation service and timer in the same way:

```bash
sudo ln -s /home/timdimm/timdimm_tng/config/timdimm-wx-rotate.service /etc/systemd/system/timdimm-wx-rotate.service
sudo ln -s /home/timdimm/timdimm_tng/config/timdimm-wx-rotate.timer /etc/systemd/system/timdimm-wx-rotate.timer
sudo systemctl daemon-reload
sudo systemctl enable --now timdimm-wx-rotate.timer
```

At 10:00 UTC the timer moves each CSV to `~/<name>-YYYY-MM-DD.csv.gz`, matching the Adafruit
archives so the three logs can be joined over the long run. Nothing is stopped first: `status.py`
opens and closes each file once per row, and the next append writes a fresh header. Check it with:

```bash
systemctl list-timers timdimm-wx-rotate.timer
journalctl -u timdimm-wx-rotate.service
```
