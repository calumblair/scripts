import http.client
import requests
import datetime
import logging
import json
import subprocess
import os
import sys


def get_preferences():
    prefs = {
    # fill these in as appropriate.
    'latitude' : 0,
        'longitude': 0,
        'metoffice_id' : "",
        'metoffice_secret': "",
        'ifttt_key': "",
        'target_ip': "",
    }
    return prefs
 

# get weather data from an external api.
# return the temperature at ~9am today.
def get_metoffice_weather(latitude, longitude, metoffice_id, metoffice_secret):
    try:
        conn = http.client.HTTPSConnection("api-metoffice.apiconnect.ibmcloud.com")
        headers = {
            'x-ibm-client-id': metoffice_id,
            'x-ibm-client-secret': metoffice_secret,
            'accept': "application/json"
        }
        req_str = "/metoffice/production/v0/forecasts/point/three-hourly?" + \
                  "excludeParameterMetadata=false&includeLocationName=true&latitude={0}&longitude={1}".format(
                   latitude, longitude)
        conn.request("GET", req_str, headers=headers)

        res = conn.getresponse()
        data = res.read()

        json_weather_params = json.loads(data.decode("utf-8"))
        location = json_weather_params['features'][0]['properties']['location']['name']
        logging.info('getting weather for {0}'.format(location))
        time_data = json_weather_params['features'][0]['properties']['timeSeries']
        today_9am = datetime.datetime.combine(datetime.date.today(), datetime.time(9, 0))
        min_delta_seconds = 24 * 60 * 60
        min_idx = None
        for t in range(0, len(time_data)):
            this_time = datetime.datetime.strptime(time_data[t]['time'], '%Y-%m-%dT%H:%MZ')
            if abs((today_9am - this_time).total_seconds()) < min_delta_seconds:
                min_delta_seconds = abs((today_9am - this_time).total_seconds())
                min_idx = t
        if min_idx is not None:
            temp_celsius = time_data[min_idx]['maxScreenAirTemp']
            temp_celsius = round(temp_celsius, 1)
            logging.info('found time closest to 9am at {0}, temperature is {1}'.format(time_data[min_idx]['time'],
                                                                                       temp_celsius))
        else:
            logging.error('failed to extract 9AM temperature from met office API ')
            temp_celsius = 20
    except Exception as e:
        temp_celsius = 20
        logging.error('failed to get Met office temperature. using {0}'.format(temp_celsius))
        logging.error('{0}'.format(e))
    return temp_celsius


# return the temperature in celsius. fetch this from the internet once per day
# and hang on to it.
def get_temperature(last_time, last_temp_celsius, latitude, longitude, metoffice_id, metoffice_secret):
    current_time = datetime.datetime.now()
    if current_time.date() == last_time.date():
        logging.info('reusing last temperature {0}'.format(last_temp_celsius))
        temp_celsius = last_temp_celsius
    else:
        temp_celsius = get_metoffice_weather(latitude, longitude, metoffice_id, metoffice_secret)
        logging.info('fetched new temperature {0}'.format(temp_celsius))
    return temp_celsius


# send a POST to the IFTTT webhook to turn on Hive heating
def turn_on_heating(temp_celsius, ifttt_key):
    result = ''
    try:
        event_name = "computer_seen"
        temp_celsius_str = '{0}'.format(temp_celsius)
        request_str = "https://maker.ifttt.com/trigger/{0}/with/key/{1}".format(event_name, ifttt_key)
        result = requests.post(request_str, params={"value1": temp_celsius_str, "value2": "none", "value3": "none"})
        logging.info('called ifttt {0} with result {1}'.format(request_str, result))
    except Exception as e:
        logging.error('failed to trigger IFTTT')
        logging.error(e)
    return result


def ping_from_windows(target_ip):
    # use Powershell
    r = subprocess.check_output(
        ['c://windows//system32//WindowsPowerShell//v1.0//powershell.exe',
         'test-connection', '-quiet', '-count 1', target_ip])
    cmd_str = str(['c://windows//system32//WindowsPowerShell//v1.0//powershell.exe',
                   'test-connection', '-quiet', '-count 1', target_ip])
    r_as_str = r.decode('utf8').strip('\r\n')
    logging.info('got {0} back from command {1}'.format(r_as_str, cmd_str))
    if r_as_str == 'True':
        return True
    if r_as_str == 'False':
        return False
    logging.error(' failed to parse return string {0}'.format(r_as_str))

    
def ping_from_linux(target_ip):
    v = subprocess.call(['ping', target_ip, '-c', '1'], stdout=subprocess.DEVNULL) 
    cmd_str = str(['ping', target_ip, '-c', '1'])
    logging.info('got {0} back from command {1}'.format(v, cmd_str))
    ret = v == 0
    return ret


# have we seen the relevant computer?
def ping_computer(target_ip):
    if os.name == 'nt':
        ret_bool = ping_from_windows(target_ip)
    else:  # linux
        ret_bool = ping_from_linux(target_ip)
    logging.info('looking for computer {0}. Seen? {1}'.format(target_ip, ret_bool))
    return ret_bool


# return a datetime with the last time this script was run, and a bool determining whether the heating was already
# triggered or not today.
def load_last_run():
    # fail safe - if we can't load data then the heating shouldn't be allowed to turn on
    heating_already_triggered = True
    last_time = datetime.datetime.now()
    temp_celsius = "Unknown"
    filename = "./last_run.json"
    try:
        with open(filename, 'r') as file:
            json_str = file.read()
        json_dict = json.loads(json_str)[0]
        last_time_epoch = json_dict['current_time']
        last_time = datetime.datetime.fromtimestamp(last_time_epoch)
        temp_celsius = json_dict['temp_celsius']
        heating_already_triggered = json_dict['heating_triggered_today']
        logging.info('loaded previous data: time: {0}, temp: {1}, heating triggered: {2}'.format(
            last_time.ctime(), temp_celsius, heating_already_triggered))
    except Exception as e:
        logging.error('failed to load previous data from {0}'.format(filename))
        logging.error(e)
    return last_time, temp_celsius, heating_already_triggered


#save last time, last temperature and whether the heating was already run today to a json file.
def save_this_run(current_time, temp_celsius, heating_triggered_today):
    epoch_time = current_time
    json_str = json.dumps(
        [{"current_time": epoch_time, "temp_celsius": temp_celsius,
          "heating_triggered_today": heating_triggered_today}]
    )
    filename = "./last_run.json"
    with open(filename, 'w') as file:
        file.write(json_str)
    logging.info("wrote data to {0}".format(filename))
    return
    

# if we don't have previous heating data, create a file for it.
def create_run_data():
    save_this_run(0,0,False)


#return true if the last time the script was run was more than 5 minutes ago
def has_enough_time_elapsed(last_time, mins=5):
    #  get current time
    current_time = datetime.datetime.now()
    # was it last run more than five minutes ago?
    sufficient_time_elapsed = (last_time + datetime.timedelta(minutes=mins)) < current_time
    logging.info('current time: {0}, last time: {1}, has enough time elapsed ?: {2}'.
                 format(current_time.ctime(), last_time.ctime(), sufficient_time_elapsed))
    return sufficient_time_elapsed, current_time.timestamp()


# determine if the script should run just now.
# it should run on weekdays between 0830 and 1000
def is_current_time_good():
    current_time = datetime.datetime.now()
    is_weekday = current_time.weekday() < 5
    valid_time_begin = datetime.time(8, 30)
    valid_time_end = datetime.time(10, 00)
    # valid_time_end = datetime.time(23, 00)
    time_valid = valid_time_begin <= current_time.time() <= valid_time_end and is_weekday
    return time_valid


#return true if the heating was already triggered on this calendar day.
def was_heating_triggered_today(last_time, last_heating_triggered):
    current_time = datetime.datetime.now()
    if current_time.date() == last_time.date():
        logging.info('same day as last run so reusing last heating triggered value: {0}'.format(last_heating_triggered))
        return last_heating_triggered
    else:
        logging.info('heating was not triggered so far today.')
        return False


def main():
    # first check: if not in the right time window then exit, don't bother logging anything.
    time_window_good = is_current_time_good()
    if not time_window_good:
        # print('time not valid - exiting')
        return 0

    prefs = get_preferences()
    # create_run_data()
    # we're in the right time period and it's a weekday.
    logging.basicConfig(filename='./heating.log', level=logging.INFO, format='%(asctime)s %(message)s')  # appends by default
    logging.info('started logging')
    # have we already run today?
    last_time, last_temp_celsius, last_heating_triggered = load_last_run()
    heating_triggered_today = was_heating_triggered_today(last_time, last_heating_triggered)
    temp_celsius = get_temperature(last_time, last_temp_celsius, 
    prefs['latitude'], prefs['longitude'], prefs['metoffice_id'], prefs['metoffice_secret'])
    run_valid, current_time_epoch = has_enough_time_elapsed(last_time)

    if not heating_triggered_today and run_valid:
        # determine whether or not to turn on heating
        is_cold = temp_celsius < 15
        computer_seen = ping_computer('192.168.0.201')
        heating_required = is_cold and computer_seen and not heating_triggered_today
        # if true, turn on heating
        if heating_required:
            logging.info('turning on heating because temperature is {0} degrees'.format(temp_celsius))
            turn_on_heating(temp_celsius, prefs['ifttt_key'])
            heating_triggered_today = True

    # log decision
    save_this_run(current_time_epoch, temp_celsius, heating_triggered_today)

    logging.info("finished script")
    return 0
    
if __name__ == "__main__":
    sys.exit(main())
