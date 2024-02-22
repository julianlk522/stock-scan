import csv
import datetime
import json
import smtplib
import sys
import traceback
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup


def main():
    """Assemble stock watchlist and send to email."""

    ## raise exception if email user and email pass not passed as args 1 and 2 
    if len(sys.argv) < 3:
        raise Exception("Email user and email pass not provided as arguments")

    try:
        scan_results = tv_scan()
        cached_tickers = get_cached_tickers()
        scores = calculate_pvs(scan_results, cached_tickers)

        update_cache(cached_tickers)

        ## sort scores
        scores = {k: v for k, v in sorted(scores.items(), key=lambda item: item[1], reverse=True)}

        return email_results(scores)
    except Exception as e:
        print(f"error: {e}\n{traceback.format_exc()}\n")
        return

def tv_scan():
    """Fetch tickers from TradingView API."""

    headers = {
        'authority': 'scanner.tradingview.com',
        'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="98", "Google Chrome";v="98"',
        'accept': 'text/plain, */*; q=0.01',
        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'sec-ch-ua-mobile': '?0',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)Chrome/98.0.4758.102 Safari/537.36', 'sec-ch-ua-platform': '"Windows"',
        'origin': 'https://www.tradingview.com',
        'sec-fetch-site': 'same-site',
        'sec-fetch-mode': 'cors',
        'sec-fetch-dest': 'empty',
        'referer': 'https://www.tradingview.com/',
        'accept-language': 'en-US,en;q=0.9,it;q=0.8'
    }

    ## SCAN SETTINGS
    # 25 tickers
    # sorted by QoQ rev. % change

    # CONDITIONS:
    # close >= $5
    # close >= 1M high * 0.8
    # 1W low >= ATH * 0.8
    # 1W value traded >= $50M
    # TTM rev. >= $200M

    # Certain industries excluded:
    # (Biotech, Casinos/Gaming, Insurance,
    # Investment Banks, O&G, Coal, etc.)
    scan_settings = {"columns":["name","description","close","total_revenue_qoq_growth_fq","country.tr","industry.tr"],"filter":[{"left":"close","operation":"in_range%","right":["high|1M",0.8,1]},{"left":"Value.Traded|1W","operation":"greater","right":50000000},{"left":"close","operation":"egreater","right":5},{"left":"total_revenue_ttm","operation":"greater","right":200000000},{"left":"industry","operation":"in_range","right":["Advertising/Marketing Services","Aerospace & Defense","Agricultural Commodities/Milling","Air Freight/Couriers","Airlines","Alternative Power Generation","Aluminum","Apparel/Footwear","Apparel/Footwear Retail","Auto Parts: OEM","Automotive Aftermarket","Beverages: Alcoholic","Beverages: Non-Alcoholic","Broadcasting","Building Products","Cable/Satellite TV","Catalog/Specialty Distribution","Chemicals: Agricultural","Chemicals: Major Diversified","Chemicals: Specialty","Commercial Printing/Forms","Computer Communications","Computer Peripherals","Computer Processing Hardware","Consumer Sundries","Containers/Packaging","Contract Drilling","Construction Materials","Data Processing Services","Department Stores","Discount Stores","Drugstore Chains","Electric Utilities","Electrical Products","Electronic Components","Electronic Equipment/Instruments","Electronic Production Equipment","Electronics Distributors","Electronics/Appliance Stores","Electronics/Appliances","Engineering & Construction","Environmental Services","Finance/Rental/Leasing","Financial Conglomerates","Financial Publishing/Services","Food Distributors","Food Retail","Food: Major Diversified","Food: Meat/Fish/Dairy","Food: Specialty/Candy","Forest Products","General Government","Home Furnishings","Home Improvement Chains","Homebuilding","Household/Personal Care","Industrial Conglomerates","Industrial Machinery","Industrial Specialties","Information Technology Services","Internet Retail","Internet Software/Services","Investment Managers","Investment Trusts/Mutual Funds","Major Telecommunications","Marine Shipping","Media Conglomerates","Metal Fabrication","Miscellaneous","Miscellaneous Commercial Services","Miscellaneous Manufacturing","Motor Vehicles","Movies/Entertainment","Office Equipment/Supplies","Other Consumer Services","Other Consumer Specialties","Other Metals/Minerals","Other Transportation","Packaged Software","Personnel Services","Precious Metals","Publishing: Books/Magazines","Publishing: Newspapers","Pulp & Paper","Railroads","Real Estate Development","Real Estate Investment Trusts","Recreational Products","Restaurants","Semiconductors","Services to the Health Industry","Specialty Stores","Specialty Telecommunications","Steel","Telecommunications Equipment","Textiles","Tools & Hardware","Trucking","Trucks/Construction/Farm Machinery","Water Utilities","Wholesale Distributors","Wireless Telecommunications","Casinos/Gaming","Major Banks"]},{"left":"low|1W","operation":"in_range%","right":["High.All",0.8,1]}],"ignore_unknown_fields":False,"options":{"lang":"en"},"price_conversion":{"to_symbol":True},"range":[0,25],"sort":{"sortBy":"total_revenue_qoq_growth_fq","sortOrder":"desc"},"markets":["america"],"filter2":{"operator":"and","operands":[{"operation":{"operator":"or","operands":[{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"stock"}},{"expression":{"left":"typespecs","operation":"has","right":["common"]}}]}}]}},{"operation":{"operator":"or","operands":[{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"stock"}},{"expression":{"left":"typespecs","operation":"has","right":["common"]}}]}},{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"stock"}},{"expression":{"left":"typespecs","operation":"has","right":["preferred"]}}]}},{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"dr"}}]}},{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"fund"}},{"expression":{"left":"typespecs","operation":"has","right":["reit"]}}]}}]}}]}}
    settings_json = json.dumps(scan_settings)

    api_url = 'https://scanner.tradingview.com/america/scan'
    resp = requests.post(api_url, data=settings_json, headers=headers)
    return resp.json()['data']

def get_cached_tickers():
    """Read cached tickers/EPS/Dividends from cache.csv"""
    with open('cache.csv') as cache:
        reader = csv.DictReader(cache)
        cached_tickers = list(reader)
        print(f"{len(cached_tickers)} cached tickers")

    return cached_tickers

def calculate_pvs(scan_results, cached_tickers):
    """Proxy Valuation Score (PVS)
    
    Calculate score for each stock based on ratio of current price to combined quarterly EPS and last dividend amount
    
    (Essentially merges current reported earnings and future expected earnings into a single score to act as a proxy for near-term valuation)
    """

    scores = {}

    for stock in scan_results:
        data = stock['d']
        ticker = data[0]
        
        qeps = get_qeps(ticker, cached_tickers)

        ## Ratio of current price:(last EPS + last dividend)
        ## standardized to score of 100
        price = data[2]
        scores[ticker] = 100 / (price / qeps) if qeps else 0
        ## e.g., $120/share, $0.75/share EPS, $0.50 dividend = 100 / ($120 / ($0.75 + $0.50)) = 100 / 96 = 1.04166667
        
    return scores

def get_qeps(ticker, cached_tickers):
    """Fetch quarterly earnings and dividend data from either cache or new scrape."""
    qeps = 0

    ## check if cached
    for row in cached_tickers:
        if row['ticker'] == ticker and row['last_earnings']:

            ## use cached EPS if fresh
            last_eps = row['last_earnings']
            last_eps_date = datetime.date.fromisoformat(last_eps)
            days_since = (datetime.date.today() - last_eps_date).days

            if days_since <= 90:
                qeps = float(row['qeps'])
            
            ## scrape for new data if older than 90 days
            else:
                cached_tickers = list(filter(lambda r: r['ticker'] != ticker, cached_tickers))
                qeps = scrape_qeps(ticker, cached_tickers)

    ## scrape for new data if not cached
    if not qeps:
        qeps = scrape_qeps(ticker, cached_tickers)

    return qeps

def scrape_qeps(ticker, cached_tickers):
    """Scrape for new earnings and dividend data, save to pending cache update
    
    (Last EPS and dividend are combined and measured against current price to calculate PVS)
    """

    url = f"https://www.alphaquery.com/stock/{ticker}/all-data-variables"
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:75.0) Gecko/20100101 Firefox/75.0', 'authority': 'www.alphaquery.com', 'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="75", "Google Chrome";v="75"', 'referer': 'https://www.alphaquery.com/stock/', 'accept': 'application/json, text/javascript, */*; q=0.01'})
    soup = BeautifulSoup(r.content, "html.parser")

    ## find latest quarterly EPS (or use 0 if not found)
    qeps = soup.find(string='Last Quarterly Earnings per Share')
    qeps = qeps.find_parent("td") if qeps else 0
    qeps = qeps.findNextSibling() if qeps else 0
    qeps = float(qeps.text) if qeps else 0

    ## find last dividend amount (or use 0 if not found)
    divid = soup.find(string='Last Dividend Amount')
    divid = divid.find_parent("td") if divid else 0
    divid = divid.findNextSibling() if divid else 0
    divid = float(divid.text) if divid and divid.text else 0

    qeps += divid

    ## find last reported earnings date
    last_eps = soup.find(string='Last Quarterly Earnings Report Date')
    last_eps = last_eps.find_parent("td") if last_eps else None
    last_eps = last_eps.findNextSibling() if last_eps else None
    last_eps = last_eps.text if last_eps else None

    ## save fresh data
    cached_tickers.append({'ticker': ticker, 'last_earnings': last_eps, 'qeps': qeps})
    return qeps

def update_cache(cached_tickers):
    """Update cache with latest earnings and dividend data."""

    with open('cache.csv', 'w', newline='') as cache:
        writer = csv.DictWriter(cache, fieldnames=['ticker', 'last_earnings', 'qeps'])
        writer.writeheader()
        for row in cached_tickers:
            writer.writerow(row)

def email_results(scores):
    """Send scores to email."""

    ## get email credentials from args 1 and 2
    email_user = sys.argv[1]
    email_p = sys.argv[2]

    if not email_user or not email_p:
        print('Error: could not get email credentials.')
        print(f'Provided: {email_user}, {email_p}')
        return

    msg = MIMEText(str(scores))
    msg['Subject'] = f"Scan Results: {datetime.date.today()}"

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(email_user, email_p)
        smtp.sendmail(email_user, to_addrs=email_user, msg=msg.as_string())

main()