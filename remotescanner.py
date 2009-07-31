#!/usr/bin/env python
#    OpenProximity2.0 is a proximity marketing OpenSource system.
#    Copyright (C) 2009,2008 Naranjo Manuel Francisco <manuel@aircable.net>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation version 2 of the License.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program; if not, write to the Free Software Foundation, Inc.,
#    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import gobject

import threading, os, traceback, time
import dbus
import dbus.service
import dbus.glib
import dbus.mainloop.glib

from re import compile

URL=	    "net.aircable.RemoteScanner"
MANAGER =   "/net/aircable/RemoteScanner/Manager"
CONNECTION= "/net/aircable/RemoteScanner"


class ConnectionFailed(dbus.DBusException):
    _dbus_error_name="%s.ConnectionFailed" % URL
    
def AddDots(address):
    address = address.strip()
    out = ""
    for i in range(0,5):
	out+=address[i*2:(i+1)*2]+":"
    out+=address[10:12]
    return out
    
class RemoteManager(dbus.service.Object):
    i = 0
    
    def handle_name_owner_changed(self, own, old, new):
	''' detect if a name owner is gone, this prevents dead locks '''
	if own in self.connections:
	    if new is None or len(new) is 0:
		for client in self.connections[own]:
		    print client.path, "lost connection, killing it"
		    client.force_disconnect()
		self.connections[own] = None

    @dbus.service.method(URL, out_signature="s", 
	    sender_keyword="sender")
    def Connect(self, sender):
	''' Connect to the manager, add disconnection handler '''
	
	path="%s/%i" % (CONNECTION, self.i)
	self.i+=1
	remote = RemoteScanner(self.bus, path)
	print sender, "connected on", path
	if sender not in self.connections:
	    self.connections[sender] = list()
	self.connections[sender].append(remote)
	return path
	
    
    def __init__(self, bus, path):
	dbus.service.Object.__init__(self, bus, path)
	self.bus=bus
	self.path=path
	self.connections=dict()
	self.bus.add_signal_receiver(self.handle_name_owner_changed,
	    'NameOwnerChanged',
	    'org.freedesktop.DBus',
	    'org.freedesktop.DBus',
	    '/org/freedesktop/DBus')
    
class RemoteScanner(dbus.service.Object):

    def __init__(self, bus, path):
	dbus.service.Object.__init__(self, bus, path)
	self.bus = bus
	self.path = path
	self.local = None
	self.remote = None
	self.record_pattern = compile("[0-9A-F]{12} RSSI.*")
	self.client = None
	
    def force_disconnect(self):
	try:
	    if self.client is not None:
		self.client.disconnect(force=True)
		# in case client died without closing connection
	        #os.system('hcitool dc %s' % self.remote)
	except Exception, err:
	    print "Failed on force_disconnect", err
	    traceback.print_exc()
    
    def connect(self):
	try:
	    self.client = sppClient(
		target = self.remote,
		channel = 1,
		service = "spp",
		device = self.local
	    )
		
	    self.client.connect()
	    time.sleep(3)

	    # empty all buffers get it to clean state
	    self.client.socket.settimeout(30)
	    print self.client.readLine()
	    print self.client.readBuffer()

    	    self.ScannerConnected(self.local, self.remote)

	except Exception, err:
	    print "Failed while connecting", err
	    traceback.print_exc()	    
	    
    def disconnect(self):
	try:
	    self.client.sendLine('c')
    	    self.client.disconnect(True)
	except Exception, err:
	    print "Failed while disconnecting", err

	self.ScannerDisconnected(self.local, self.remote)
	self.client = None

    def scan(self, times=1):
	try:
	    self.PropertyChanged('Discovering', 1)
	    threading.Thread(target=self.__scan, args=(times, )).start()
	except Exception, err:
	    traceback.print_exc()
	    print "Failed on scan start", err

    def __scan(self, times):
	try:
	    self.client.socket.settimeout(30)
	    self.client.sendLine("r%i" % times) 
	    print self.client.readBuffer()

	    flag = True
	    while ( flag ):
		lines=self.client.readBuffer(honnor_eol=True,timeout=1)

		for line in lines.splitlines():
		    if self.record_pattern.match(line.strip()):
			address, rssi = line.split('RSSI')
			self.DeviceFound( AddDots(address) , {'RSSI': int(rssi)})
		    elif line.find('COMMAND') >-1:
			print "RSSI completed"
			flag = False
			break
	except (SPPException, SPPNotConnectedException, TypeError), e:
	    print "error while scanning, could be that we lost connection", e
	except Exception, err:
	    traceback.print_exc()	
	    self.disconnect()
	
	self.PropertyChanged('Discovering', 0)
	return False
    
    @dbus.service.signal(URL, signature="s")
    def ConnectionException(self, text):
	print "ConnectionException", text
    
    @dbus.service.signal(URL, signature="sa{si}")
    def DeviceFound(self, address, values):
	# simulate bluez format
	print "Found %s: %s" % (address, values )
	
    @dbus.service.signal(URL, signature="ss")
    def ScannerConnected(self, local, remote):
	print "ScannerConnected %s: %s" % (local, remote )

    @dbus.service.signal(URL, signature="ss")
    def ScannerDisconnected(self, local, remote):
	print "ScannerDisconnected %s: %s" % (local, remote )
	
    @dbus.service.signal(URL, signature="si")
    def PropertyChanged(self, name, value):
	print "PropertyChanged %s: %s" % (name, value)
    
    @dbus.service.method(URL, in_signature="i", out_signature="")
    def StartScan(self, times=1):
	print "StartScan"
	self.scan(times)
	return
	
    @dbus.service.method(URL, in_signature="ss", out_signature="")
    def Connect(self, local, remote):
	print "Connect", str(local), str(remote)
	self.local = str(local)
	self.remote = str(remote)
	print "Connect", self.local, self.remote
	threading.Thread(target=self.connect).start()
	return

    @dbus.service.method(URL)
    def Disconnect(self):
	print "Disconnect"
	threading.Thread(target=self.disconnect).start()
	return
	
    @dbus.service.method(URL, out_signature="b")
    def isConnected(self):
	if self.client is None:
	    return False
	return self.client.socket is not None

if __name__=='__main__':
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    gobject.threads_init()
    dbus.glib.init_threads()
    
    bus = dbus.SystemBus()
    #bus = dbus.SessionBus()
    name = dbus.service.BusName(URL, bus)
    object = RemoteManager( bus, MANAGER )
    
    from net.aircable.spp import sppClient
    from net.aircable.spp.errors import SPPException, SPPNotConnectedException
    mainloop = gobject.MainLoop()
    print "Running RemoteScanner Service."
    mainloop.run()
