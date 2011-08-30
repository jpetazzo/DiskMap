#!/usr/bin/env python

import subprocess, re, os, sys, readline, cmd, pickle
from pprint import pformat, pprint

cachefile = "/tmp/pouet"

sas2ircu = "/usr/sbin/sas2ircu"
prtconf = "/usr/sbin/prtconf"

def run(cmd, *args):
    args = tuple([ str(i) for i in args ])
    return subprocess.Popen((cmd,) + args,
                            stdout=subprocess.PIPE).communicate()[0]

def cleandict(mydict, *toint):
    result = {}
    for k in mydict.keys():
        result[k] = long(mydict[k]) if k in toint else mydict[k].strip()
    return result

def megabyze(i, fact=1000):
    """
    Return the size in Kilo, Mega, Giga, Tera, Peta according to the input.
    """
    i = float(i)
    for unit in "", "K", "M", "G", "T", "P":
        if i < 2000: break
        i = i / fact
    return "%.1f%s"%(i, unit)

class SesManager(cmd.Cmd):
    def __init__(self, *l, **kv):
        cmd.Cmd.__init__(self, *l, **kv)
        self._enclosures = {}
        self._controllers = {}
        self._disks = {}
        self.prompt = "Diskmap> "

    @property
    def disks(self):
        return dict([ (k, v) for k, v in self._disks.items() if k.startswith("/dev/rdsk/") ])

    @property
    def enclosures(self):
        return self._enclosures

    @property
    def controllers(self):
        return self._controllers

    def discover_controllers(self):
        """ Discover controller present in the computer """
        tmp = run(sas2ircu, "LIST")
        tmp = re.findall("(\n +[0-9]+ +.*)", tmp)
        for ctrl in tmp:
            ctrl = ctrl.strip()
            m = re.match("(?P<id>[0-9]) +(?P<adaptertype>[^ ].*[^ ]) +(?P<vendorid>[^ ]+) +"
                         "(?P<deviceid>[^ ]+) +(?P<pciadress>[^ ]*:[^ ]*) +(?P<subsysvenid>[^ ]+) +"
                         "(?P<subsysdevid>[^ ]+) *", ctrl)
            if m:
                m = cleandict(m.groupdict(), "id")
                self._controllers[m["id"]] = m

    def discover_enclosures(self, *ctrls):
        """ Discover enclosure wired to controller. If no controller specified, discover them all """
        if not ctrls:
            ctrls = self.controllers.keys()
        for ctrl in ctrls:
            tmp = run(sas2ircu, ctrl, "DISPLAY")
            #tmp = file("/tmp/pouet.txt").read() # Test with Wraith__ setup
            enclosures = {}
            # Discover enclosures
            for m in re.finditer("Enclosure# +: (?P<index>[^ ]+)\n +"
                                 "Logical ID +: (?P<id>[^ ]+)\n +"
                                 "Numslots +: (?P<numslot>[0-9]+)", tmp):
                m = cleandict(m.groupdict(), "index", "numslot")
                m["controller"] = ctrl
                self._enclosures[m["id"]] = m
                enclosures[m["index"]] = m
            # Discover Drives
            for m in re.finditer("Device is a Hard disk\n +"
                                 "Enclosure # +: (?P<enclosureindex>[^\n]+)\n +"
                                 "Slot # +: (?P<slot>[^\n]+)\n +"
                                 "State +: (?P<state>[^\n]+)\n +"
                                 "Size .in MB./.in sectors. +: (?P<sizemb>[^/]+)/(?P<sizesector>[^\n]+)\n +"
                                 "Manufacturer +: (?P<manufacturer>[^\n]+)\n +"
                                 "Model Number +: (?P<model>[^\n]+)\n +"
                                 "Firmware Revision +: (?P<firmware>[^\n]+)\n +"
                                 "Serial No +: (?P<serial>[^\n]+)\n +"
                                 "Protocol +: (?P<protocol>[^\n]+)\n +"
                                 "Drive Type +: (?P<drivetype>[^\n]+)\n"
                                 , tmp):
                m = cleandict(m.groupdict(), "enclosureindex", "slot", "sizemb", "sizesector")
                m["enclosure"] = enclosures[m["enclosureindex"]]["id"]
                m["controller"] = ctrl
                self._disks[m["serial"]] = m

    def discover_mapping(self):
        """ use prtconf to get real device name using disk serial """
        tmp = run(prtconf, "-v")
        # Do some ugly magic to get what we want
        # First, get one line per drive
        tmp = tmp.replace("\n", "").replace("disk, instance", "\n")
        # Then match with regex
        tmp = re.findall("name='inquiry-serial-no' type=string items=1 dev=none +value='([^']+)'"
                         ".*?"
                         "name='client-guid' type=string items=1 *value='([^']+)'", tmp)
        # Capitalize everything.
        tmp = [ (a.upper(), b.upper()) for a, b in tmp ]
        tmp = dict(tmp)
        # Sometimes serial returned by prtconf and by sas2ircu are different. Mangle them
        for serial, device in tmp.items()[:]:
            serial = serial.strip()
            serial = serial.replace("WD-", "WD")
            device = "/dev/rdsk/c1t%sd0"%device
            if serial in self._disks:
                # Add device name to disks
                self._disks[serial]["device"] = device
                # Add a reverse lookup
                self._disks[device] = self._disks[serial]
            else:
                print "Warning : Got the serial %s from prtconf, but can't find it in disk detected by sas2ircu (disk removed ?)"%serial

    def set_leds(self, disks, value=True):
        print "Turning leds", "on" if value else "off",
        for disk in disks:
            print disks
            run(sas2ircu, disk["controller"], "LOCATE", "%(enclosureindex)s:%(slot)s"%disk, "on" if value else "off")
            print ".",
        print

    def preloop(self):
        if os.path.exists(cachefile):
            self.do_load("")
        else:
            self.do_discover("")
            self.do_save("")

    def do_quit(self, line):
        "Quit"
        return True
    do_EOF = do_quit
        
    def do_discover(self, line=""):
        """Perform discovery on host to populate controller, enclosures and disks """
        self.discover_controllers()
        self.discover_enclosures()
        self.discover_mapping()
        self.do_save("")
    do_refresh = do_discover

    def do_save(self, line):
        """Save data to cache file"""
        pickle.dump((self.controllers, self.enclosures, self._disks), file(cachefile, "w+"))


    def do_load(self, line):
        """Load data from cache file"""
        self.controllers, self.enclosures, self._disks = pickle.load(file(cachefile))

    def do_enclosures(self, line):
        """Display detected enclosures"""
        pprint(self.enclosures)

    def do_controllers(self, line):
        """Display detected controllers"""
        pprint(self.controllers)

    def do_disks(self, line):
        """Display detected disks. Use -v for verbose output"""
        list = [ ("%1d:%.2d:%.2d"%(v["controller"], v["enclosureindex"], v["slot"]), v)
                 for k,v in self.disks.items() ]
        list.sort()
        if line == "-v":
            pprint (list)
            return
        for path, disk in list:
            disk["path"] = path
            disk["device"] = disk["device"].replace("/dev/rdsk/", "")
            disk["readablesize"] = megabyze(disk["sizemb"]*1024*1024)
            print "%(path)s  %(device)23s  %(model)16s  %(readablesize)6s  %(state)s"%disk

    def do_ledon(self, line):
        """ Turn on locate led on parameters FIXME : syntax parameters"""
        pass

    def do_ledoff(self, line):
        """ Turn on locate led on parameters FIXME : syntax parameters"""
        if line == "all":
            self.set_leds(self.disks, False)
    
    def __str__(self):
        result = []
        for i in ("controllers", "enclosures", "disks"):
            result.append(i.capitalize())
            result.append("="*80)
            result.append(pformat(getattr(self,i)))
            result.append("")
        return "\n".join(result)



if __name__ == "__main__":
    #if not os.path.isfile(sas2ircu):
    #    sys.exit("Error, cannot find sas2ircu (%s)"%sas2ircu)
    sm = SesManager()
    if len(sys.argv) > 1:
        sm.preloop()
        sm.onecmd(" ".join(sys.argv[1:]))
    else:
        sm.cmdloop()
    
    
