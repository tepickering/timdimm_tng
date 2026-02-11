# kstars specific files

## stored here

- **kstars_docker**: script to run `kstars` from a docker container. never really worked properly, but hasn't been tested
again in a while. `kstars` interacts a lot with the local system to spawn scripts and INDI servers so i think it has to be
run either completely within docker or not use docker at all. 
- **kstarsrc**: file that is found in `~/.config` where `kstars` saves its state and other configuration information.

## stored elsewhere

- **~/kstars_config.tgz**: this is a backup of the directory `~/.local/share/kstars`. it contains a lot of database
files and configuration data. most importantly, this is where the index files are stored that the plate solving uses.
the backup was last performed 2026-02-10.

if for some reason the timdimm software needs to be set up on a new machine, it will probably save a lot of time to
place `kstarsrc` in `~/.config` and unpack `~/kstars_config.tgz` in `~/.local/share` before running `kstars`.

