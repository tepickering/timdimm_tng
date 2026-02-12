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
