#!/usr/bin/python3

import sys, os
# Add relative paths for the directory where the adapter is located as well as the parent
sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__),'../../base'))

from sofabase import sofabase, adapterbase, configbase
import devices

import math
import random
import json
import asyncio
import aiohttp
import datetime

class rainmachine(sofabase):

    class adapter_config(configbase):
    
        def adapter_fields(self):
            self.device_password=self.set_or_default('device_password', mandatory=True)
            self.device_address=self.set_or_default('device_address', mandatory=True)
            self.device_port=self.set_or_default('device_port', default=8080)
            self.device_api=self.set_or_default('device_api', default={"version": { "command": "get", "url": "/api/apiVer"}, "getToken": { "command": "post","url": "/api/4/auth/login"}}) 


    class EndpointHealth(devices.EndpointHealth):

        @property            
        def connectivity(self):
            #stubbed out but should reflect whether the panel is connected or not
            return 'OK'
            
            
    class TemperatureSensor(devices.TemperatureSensor):
        
        @property            
        def temperature(self):
            try:
                return round(self.nativeObject['weather']['temperature'])
            except:
                self.log.error('!! error getting weather temperature: %s' % self.nativeObject.keys(), exc_info=True)
            return 0
            
            
    class adapterProcess(adapterbase):
        
        conditions=[    "MostlyCloudy", "Fair", "FewClouds", "PartlyCloudy", "Overcast", "Fog", "Smoke", "FreezingRain", "IcePellets",
                        "RainIce", "RainSnow", "RainShowers", "Thunderstorm", "Snow", "Windy", "ShowersInVicinity", "HeavyFreezingRain",
                        "ThunderstormInVicinity", "LightRain", "HeavyRain", "FunnelCloud", "Dust", "Haze", "Hot", "Cold", "Unknown" ]
    
        def __init__(self, log=None, loop=None, dataset=None, notify=None, request=None, config=None, **kwargs):
            self.config=config
            self.dataset=dataset
            self.dataset.nativeDevices['zones']=[]
            self.dataset.nativeDevices['machines']=[]
            self.log=log
            self.notify=notify
            self.polltime=30  

            if not loop:
                self.loop = asyncio.new_event_loop()
            else:
                self.loop=loop
            
        async def pre_activate(self):
            self.log.info('.. Starting rainmachine')
            self.access_token=await self.get_auth_token()
            #self.log.info('Token data: %s' % self.tokendata)
            await self.update_provision()
            await self.get_api('dailystats')
            await self.get_zones()
            asyncio.create_task(self.pollRainMachine())
            
        async def start(self):
            self.log.info('.. Starting rainmachine main process')            
        
        async def pollRainMachine(self):
            while True:
                try:
                    await self.update_data()
                except:
                    self.log.error('Error fetching Rain Machine Data', exc_info=True)
                
                await asyncio.sleep(self.polltime)

        async def update_provision(self):
            try:
                response=await self.get_api('/provision')
                self.device_name=response['system']['netName']
                await self.dataset.ingest( { "machines": { self.device_name: { "name": self.device_name, "provision": response }}} )
            except:
                self.log.error('!! Error getting updated lcoation data from rain machine', exc_info=True)

                
        async def update_data(self):
            try:
                response=await self.get_api('/mixer/%s' % datetime.datetime.now().strftime("%Y-%m-%d"))
                await self.dataset.ingest({ "machines": { self.device_name: { "weather" : await self.parse_mixer(response) }}} )

            except:
                self.log.error('!! Error getting updated data from rain machine', exc_info=True)
            
        async def parse_mixer(self, data):
            try:
                weatherdata=data['mixerDataByDate'][0]
                weatherdata['conditionName']=self.conditions[int(weatherdata['condition'])]
                for item in weatherdata:
                    if item in ['temperature','minTemp','maxTemp']:
                        weatherdata[item]=(int(weatherdata[item]) * 9/5) + 32
                #await self.dataset.ingest({ "weather" : weatherdata })
                return weatherdata
            except:
                self.log.error('!! error ingesting weather data: %s' % data, exc_info=True)
                return {}
            
        async def get_zones(self):
            try:
                zonedata=await self.get_api('zone')
                await self.dataset.ingest(zonedata)
                for zone in zonedata['zones']:
                    if zone['active']:
                        await self.dataset.ingest({ "machines": { self.device_name: { "zones": { "zone-%s" % str(zone['uid']) : zone }}}})
                        self.log.info('Zone: %s %s' % (zone['name'],zone))
            except:
                self.log.error('Error getting zones', exc_info=True)            
            
        async def get_auth_token(self):
            try:
                data=json.dumps({"pwd": self.config.device_password})
                url="https://%s:%s/api/4/auth/login" % (self.config.device_address, self.config.device_port)
                headers={}
                #headers = { "Content-type": "text/xml" }
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as client:
                    response=await client.post(url, data=data, headers=headers)
                    result=await response.read()
                    result=json.loads(result.decode())
                    self.tokendata=result
                    
                return self.tokendata["access_token"]
            except:
                self.log.error('Error getting auth token', exc_info=True)
                
        async def get_api(self, api_command):
            
            try:
                url="https://%s:%s/api/4/%s?access_token=%s" % (self.config.device_address, self.config.device_port, api_command, self.access_token)
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as client:
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
        async def addSmartDevice(self, path):
            
            try:
                device_id=path.split("/")[2]
                device_type=path.split("/")[1]
                endpointId="%s:%s:%s" % ("rainmachine", device_type, device_id)
                if endpointId not in self.dataset.localDevices:  # localDevices/friendlyNam                
                    if device_type=="machines":
                        nativeObject=self.dataset.nativeDevices[device_type][device_id]
                        return await self.add_machine(device_id, nativeObject)
            except:
                self.log.error('Error defining smart device', exc_info=True)
                return False


        async def add_machine(self, deviceid, nativeObject):
            try:
                if 'weather' in nativeObject:  # shim right now to wait for first weather update
                    self.log.info('~~ Adding %s %s' % (deviceid, nativeObject))
                    device=devices.alexaDevice('rainmachine/machines/%s' % deviceid, "Outdoor Temperature", displayCategories=['TEMPERATURE_SENSOR'], adapter=self)
                    device.TemperatureSensor=rainmachine.TemperatureSensor(device=device)
                    device.EndpointHealth=rainmachine.EndpointHealth(device=device)
                    return self.dataset.add_device(device)
            except:
                self.log.error('!! Error defining smart device', exc_info=True)
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
