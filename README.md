## Installation

```
pip install -r requirements.txt
```

## Run

### Linux

```
python3 "{path-to-project-directory}/scan.py" "{gmail address}" "{associated gmail app password}"
```

### Windows

```
python "{path-to-project-directory}/scan.py" "{gmail address}" "{associated gmail app password}"
```

or if Python is not in the PATH variable:

```
{path-to-python}/python.exe "{path-to-project-directory}/scan.py" "{gmail address}" "{associated gmail app password}"
```

## Example Results

Stocks in scan results are ranked by Proxy Valuation Score

```
PVS = 100 / (Price / (Quarterly EPS + Quarterly Dividend))
```

**Subject**: Scan Results: 2024-10-16

**Message Body**:

### Watchlist:

<ol>
<li>CTVA: 2.47</li>
<li>PNW: 2.03</li>
<li style='color: #FF0000;'>BECN: 1.49</li>
<li>FTDR: 1.47</li>
<li>CHDN: 1.36</li>
<li style='color: #FF0000;'>GVA: 1.29</li>
<li>SUM: 0.67</li>
<li>AZO: 0.55</li>
<li>CSL: 0.54</li>
<li>WSO: 0.46</li>
...
</ol>
