#!/usr/bin/python3

import sys, os
# Add relative paths for the directory where the adapter is located as well as the parent
sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__),'../../base'))

from sofabase import sofabase
from sofabase import adapterbase
import devices


import math
import random
import json
import asyncio
import aiohttp


class rainmachine(sofabase):
    
    class adapterProcess(adapterbase):
    
        def __init__(self, log=None, loop=None, dataset=None, notify=None, request=None, **kwargs):
            self.dataset=dataset
            self.dataset.nativeDevices['target']={}
            self.log=log
            self.notify=notify
            self.polltime=5

            if not loop:
                self.loop = asyncio.new_event_loop()
            else:
                self.loop=loop
            
        async def start(self):
            self.log.info('.. Starting rainmachine')
            self.access_token=await self.get_auth_token()
            #self.log.info('Token data: %s' % self.tokendata)
            await self.get_api('dailystats')
            await self.get_zones()
            self.log.info('%s' % json.dumps(await self.get_api('/mixer/2020-01-06')))
            self.log.info('%s' % await self.get_api('/watering/zone'))
            
        async def get_zones(self):
            try:
                zonedata=await self.get_api('zone')
                for zone in zonedata['zones']:
                    if zone['active']:
                        self.log.info('Zone: %s %s' % (zone['name'],zone))
            except:
                self.log.error('Error getting zones', exc_info=True)            
            
        async def get_auth_token(self):
            try:
                data=json.dumps({"pwd": self.dataset.config['password']})
                url="https://%s:%s/api/4/auth/login" % (self.dataset.config['device_address'], self.dataset.config['device_port'])
                headers={}
                self.log.info('URL: %s %s'  % (url, data))
                #headers = { "Content-type": "text/xml" }
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False)) as client:
                    response=await client.post(url, data=data, headers=headers)
                    result=await response.read()
                    result=json.loads(result.decode())
                    self.tokendata=result
                    
                return self.tokendata["access_token"]
            except:
                self.log.error('Error getting auth token', exc_info=True)
                
        async def get_api(self, api_command):
            
            try:
                url="https://%s:%s/api/4/%s?access_token=%s" % (self.dataset.config['device_address'], self.dataset.config['device_port'], api_command, self.access_token)
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False)) as client:
                    async with client.get(url) as response:
                        status=response.status
                        result=await response.text()
                        #self.log.info('result: %s' % result)
                        
                if result:
                    return json.loads(result)
                    
                self.log.warn('.! No Result returned')            
                return {}
    
            except:
                self.log.error("Error requesting state for %s" % target, exc_info=True)
                return {}
            


        # Adapter Overlays that will be called from dataset
        def addSmartDevice(self, path):
            
            try:
                if path.split("/")[1]=="target":
                    return self.addSmartPost(path.split("/")[2])

            except:
                self.log.error('Error defining smart device', exc_info=True)
                return False


        async def addSmartPost(self, deviceid):
            
            nativeObject=self.dataset.nativeDevices['target'][deviceid]
            if nativeObject['name'] not in self.dataset.localDevices:
                return self.dataset.addDevice(nativeObject['name'], devices.basicDevice('post/target/%s' % deviceid, nativeObject['name'], native=nativeObject))
            
            return False


        async def executePost(self, target, command, data=""):
            
            try:
                url=self.targets[target][command]
                headers = { "Content-type": "text/xml" }
                async with aiohttp.ClientSession() as client:
                    response=await client.post(url, data=data, headers=headers)
                    result=await response.read()
                    result=json.loads(result.decode())
                    self.log.info('Post result: %s' % result)
                    return result
                
                self.log.warn('.! No Result returned')            
                return {}
    
            except:
                self.log.error("Error requesting state for %s" % endpointId,exc_info=True)
                return {}

        async def executeGet(self, target, command):
            
            try:
                url=self.targets[target][command]
                async with aiohttp.ClientSession() as client:
                    async with client.get(url) as response:
                        status=response.status
                        result=await response.text()
                
                if result:
                    await self.dataset.ingest({"target": { target : { "status": command=="on" }}})
                    self.log.info('.. Get result: %s' % result)
                    return result
                    
                self.log.warn('.! No Result returned')            
                return {}
    
            except:
                self.log.error("Error requesting state for %s" % target, exc_info=True)
                return {}



        async def processDirective(self, endpointId, controller, command, payload, correlationToken='', cookie={}):

            try:
                device=endpointId.split(":")[2]

                if controller=="PowerController":
                    if command=='TurnOn':
                        response=await self.executeGet(device, 'on')
                    elif command=='TurnOff':
                        response=await self.executeGet(device, 'off')

                response=await self.dataset.generateResponse(endpointId, correlationToken)    
                return response
            except:
                self.log.error('Error executing state change.', exc_info=True)


        def virtualControllers(self, itempath):

            try:
                nativeObject=self.dataset.getObjectFromPath(self.dataset.getObjectPath(itempath))
                self.log.debug('Checking object for controllers: %s' % nativeObject)
                
                try:
                    detail=itempath.split("/",3)[3]
                except:
                    detail=""

                controllerlist={}
                if detail=="on" or detail=="":
                    controllerlist["PowerController"]=["powerState"]

                return controllerlist
            except KeyError:
                pass
            except:
                self.log.error('Error getting virtual controller types for %s' % itempath, exc_info=True)


        def virtualControllerProperty(self, nativeObj, controllerProp):
            
            try:
                if controllerProp=='powerState':
                    return "ON" if nativeObj['status'] else "OFF"
                else:
                    self.log.info('Unknown controller property mapping: %s' % controllerProp)
                    return {}
            except:
                self.log.error('Error converting virtual controller property: %s %s' % (controllerProp, nativeObj), exc_info=True)
                
                


if __name__ == '__main__':
    adapter=rainmachine(name='rainmachine')
    adapter.start()
