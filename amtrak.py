import requests
import json
import re
import numpy as np
from bs4 import BeautifulSoup
from math import cos, asin, sqrt
import pickle
import pprint
import os

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.expected_conditions import NoAlertPresentException
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from math import cos, asin, sqrt
import demjson
import datetime
import sys
base_path = os.path.split(os.path.realpath(__file__))[0]


import warnings
warnings.filterwarnings("ignore", category=UserWarning, module='bs4')

def strip_ansi_color_codes(text):
    ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', text)

def get_latlon():
    text = requests.get('http://ip-api.com').text
    soup = BeautifulSoup(text)
    try:
        body_text = soup.select('body')[0].text.strip()
    except IndexError:
        # sometimes the body tags dont show up... weird
        body_text = text.strip()
    body_text = body_text.strip("'<>() ").replace('\'', '\"')

    json_resp = json.loads(strip_ansi_color_codes(body_text))
    return json_resp['lat'], json_resp['lon']

def get_amtrak_city_info():
    with open(os.path.join(base_path, 'amtrak_station_page.htm'), 'r') as f:
        soup = BeautifulSoup(f.read())
    # get all tables on the page.
    tables = soup.select('tbody')
    # filter station tables
    station_tables = []
    for table in tables:
        headers = table.select('th')
        # throw out all the tables that dont look like station tables.
        if headers == [] or headers[0].text != 'Station':
            continue
        station_tables.append(table)

    city_info = []
    for table in station_tables:
        rows = table.select('tr')[1:]
        for row in rows:
            columns = row.select('td')
            try:
                city_name = columns[1].select('a')[0].text
                city_link = columns[1].select('a')[0]['href']
                station_code = columns[3].text
            except IndexError:
                # this happens when an entry in the table is malformed.
                continue
            city_info.append((city_name, city_link, station_code))
    return city_info

def collect_static_city_files(city_links):
    base_url = 'https://en.wikipedia.org/'
    driver = webdriver.Chrome(executable_path='./chromedriver 4')
    for city_link in city_links:
        driver.get(city_link)
        try:
            WebDriverWait(driver, 100).until(expected_conditions.presence_of_element_located((By.CSS_SELECTOR, '.geo-nondefault')))
        except TimeoutException:
            print(f'Could not find data for {city_link}')
            continue
        soup = BeautifulSoup(driver.page_source)
        geo_default = soup.select('.geo-nondefault')
        if not geo_default:
            print(f'Could not find geo-default for {city_link}')
            continue
        try:
            latlong_string = geo_default[0].select('.geo-dec')[0].text
            print(f'{city_link}\t {latlong_string}')
        except IndexError:
            print(f'Could not find latlong string for {city_link}')

def produce_datasheet(city_info):
    # read in the collection output for city latlon
    with open('cities_without_data', 'w') as f:
        pass
    cities_without_data = open(os.path.join(base_path, 'cities_without_data'), 'a')
    with open('static_city_collection_output', 'r') as f:
        lines = [x.strip() for x in f.readlines()]

    url_to_latlon_mapping = dict()
    for line in lines:
        success_match = re.match(r'^(.*?)\t(.*?)$', line)
        if success_match:
            (url, latlon_string) = success_match.groups()
            lat, lon = re.match(r'^([\d\.]+).*?([\d\.]+).*?$', latlon_string.strip()).groups()
            lat, lon = float(lat), float(lon)
            url_to_latlon_mapping[url] = (lat, lon)
        else:
            print(line, file=cities_without_data)
    cities_without_data.close()
    # add the lat and lons onto the station-page data.
    complete_data = []
    for (city_name, city_link, station_code) in city_info:
        if city_link in url_to_latlon_mapping:
            lat, lon = url_to_latlon_mapping[city_link]
        else:
            lat, lon = None, None
        print((city_name, city_link, station_code.strip(), lat, lon))
        complete_data.append((city_name, city_link, station_code.strip(), lat, lon))
    # remove duplicates
    filtered_complete_data = []
    station_code_set = set()
    for i in range(len(complete_data)):
        (city_name, city_link, station_code, lat, lon) = complete_data[i]
        if station_code in station_code_set:
            continue
        station_code_set.add(station_code)
        filtered_complete_data.append((city_name, city_link, station_code, lat, lon))
    with open(os.path.join(base_path, 'complete_data.pickle'), 'wb') as f:
        pickle.dump(filtered_complete_data, f)


def latlon_distance(lat1, lon1, lat2, lon2):
    p = 0.017453292519943295     #Pi/180
    a = 0.5 - cos((lat2 - lat1) * p)/2 + cos(lat1 * p) * cos(lat2 * p) * (1 - cos((lon2 - lon1) * p)) / 2
    return 12742 * asin(sqrt(a)) #2*R*asin...


def compute_closest_city():
    with open(os.path.join(base_path, 'complete_data.pickle'), 'rb') as f:
        complete_data = pickle.load(f)
    closest_city = None
    closest_distance = np.inf
    my_lat, my_lon = get_latlon()
    # mega hax because amtrak is only in the western hemisphere.
    my_lon = -my_lon
    for data in complete_data:
        lat, lon = data[-2], data[-1]
        if (lat is None) or (lon is None):
            continue
        distance = latlon_distance(my_lat, my_lon, lat, lon)
        if distance < closest_distance:
            closest_distance = distance
            closest_city = data
    return closest_city, closest_distance




def request_amtrak_information(station_code, train_number):
    today = datetime.datetime.today().strftime('%m/%d/%Y')

    post_params = {
        'wdf_trainNumber': f'{train_number}',
        'wdf_destination': f'{station_code}',
        'statesType': 'AB',
        'countryType': 'US',
        'radioSelect': 'arrivalTime',
        'wdf_SortBy': 'arrivalTime',
        '/sessionWorkflow/productWorkflow[@product=\'Rail\']/tripRequirements/journeyRequirements[1]/departDate.usdate': f'{today}',
        'requestor': 'amtrak.presentation.handler.page.AmtrakCMSNavigationTabPageHandler',
        '/sessionWorkflow/productWorkflow[@product=\'Rail\']/tripRequirements/@trainStatusType': 'statusByTrainNumber',
        'xwdf_SortBy': '/sessionWorkflow/productWorkflow[@product=\'Rail\']/tripRequirements/journeyRequirements[1]/departDate/@radioSelect',
        'xwdf_origin': '/sessionWorkflow/productWorkflow[@product=\'Rail\']/travelSelection/journeySelection[1]/departLocation/search',
        'wdf_origin value': '',
        'wdf_origin': '',
        'xwdf_destination': '/sessionWorkflow/productWorkflow[@product=\'Rail\']/travelSelection/journeySelection[1]/arriveLocation/search',
        'xwdf_trainNumber': '/sessionWorkflow/productWorkflow[@product=\'Rail\']/tripRequirements/journeyRequirements[1]/segmentRequirements[1]/serviceCode',
        '_handler=amtrak.presentation.handler.request.rail.AmtrakRailTrainStatusSearchRequestHandler/_xpath=/sessionWorkflow/productWorkflow[@product=\'Rail\']': 'SEARCH:',
    }
    post_url = 'https://tickets.amtrak.com/itd/amtrak'
    resp = requests.post(post_url, post_params)
    soup = BeautifulSoup(resp.text)
    scripts = soup.select('script')
    # find the first script that contains the TrainStatus object.
    for script in scripts:
        text = script.text
        if 'TrainStatus:' in text:
            train_status_string = scan_until_balanced(text, text.find('TrainStatus:'), '{', '}')
            compliant_ts_string = '{'+train_status_string+'}'
            train_status = demjson.decode(compliant_ts_string)
            assert len(train_status['TrainStatus']['item']) == 1
            base = train_status['TrainStatus']['item'][0]
            departure_status = base['departureTrainStatus'].strip()
            scheduled_arrive_time = base['ScheduledArriveTime'].strip()
            estimated_arrive_time = base['EstimatedArriveTime'].strip()
            arrive_train_status = base['ArriveTrainStatus'].strip()
            return {'departure_status' : departure_status,
                    'scheduled_arrive_time': scheduled_arrive_time,
                    'estimated_arrive_time': estimated_arrive_time,
                    'arrive_train_status': arrive_train_status}
    return None


def scan_until_balanced(string, starting_pos, left_symbol, right_symbol):
    before_first_occurance = True
    num_left, num_right = 0, 0
    ending_pos = starting_pos
    while before_first_occurance or (num_left != num_right):
        if num_right > num_left:
            raise Exception(f'Number of "{right_symbol}" characters exceeds number of "{left_symbol}" characters.')
        char = string[ending_pos]
        if char == left_symbol:
            num_left += 1
            before_first_occurance = False
        if char == right_symbol:
            num_right += 1
        ending_pos += 1
    return string[starting_pos:ending_pos]


if __name__ == '__main__':
    train_number = int(sys.argv[1].strip())
    pp = pprint.PrettyPrinter(indent=4)
    (city_name, city_link, station_code, lat, lon), _ = compute_closest_city()
    pp.pprint(request_amtrak_information(station_code, train_number))
