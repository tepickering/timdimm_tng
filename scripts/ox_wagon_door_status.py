#!/usr/bin/python3

# script to test status of ox-wagon door

import subprocess
import os
import sys
import re
import shlex


class singleinstance(object):
    '''
    singleinstance - based on Windows version by Dragan Jovelic this is a Linux
                     version that accomplishes the same task: make sure that
                     only a single instance of an application is running.

    '''

    def __init__(self, pidPath):
        '''
        pidPath - full path/filename where pid for running application is to be
                  stored.  Often this is ./var/<pgmname>.pid
        '''
        self.pidPath=pidPath
        #
        # See if pidFile exists
        #
        if os.path.exists(pidPath):
            #
            # Make sure it is not a "stale" pidFile
            #
            pid=open(pidPath, 'r').read().strip()
            #
            # Check list of running pids, if not running it is stale so
            # overwrite
            #
            try:
                os.kill(int(pid), 0)
                pidRunning = 1
            except OSError:
                pidRunning = 0
                if pidRunning:
                    self.lasterror=True
                else:
                    self.lasterror=False
        else:
            self.lasterror=False

        if not self.lasterror:
            #
            # Write my pid into pidFile to keep multiple copies of program from
            # running.
            #
            fp = open(pidPath, 'w')
            fp.write(str(os.getpid()))
            fp.close()

    def alreadyrunning(self):
        return self.lasterror

    def __del__(self):
        if not self.lasterror:
            os.unlink(self.pidPath)

def command_run_get_output(cmd):
        p = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        droproof=grep("Drop Roof Closed.*True", out.decode().splitlines())
        slideroof=grep("Slide Roof Closed.*True", out.decode().splitlines())
        return droproof,slideroof

def grep(pattern,word_list):
        expr = re.compile(pattern)
        return [elem for elem in word_list if expr.search(elem)]

command="/home/timdimm/conda/envs/timdimm/bin/oxwagon STATUS"
oxwagon_status = singleinstance('/home/timdimm/ox_wagon_status.pid')

if oxwagon_status.alreadyrunning():
	print("Already running")
	sys.exit(0)
else:
	droproof,slideroof=command_run_get_output(command)
	if droproof and slideroof:
		print("OK: Drop roof and slide roof CLOSED")
		sys.exit(0)
	elif not droproof and not slideroof:
		print("CRITICAL: Drop roof and slide roof OPEN")
		sys.exit(2)
	elif not slideroof:
		print("CRITICAL: Slide roof OPEN")
		sys.exit(2)
	elif not droproof:
		print("CRITICAL: Drop roof OPEN")
		sys.exit(2)

