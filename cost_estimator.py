"""Estimate only; no API requests. Prices/tokens/FX are explicit user inputs."""
import argparse,json
p=argparse.ArgumentParser(description=__doc__)
for flag,kind,default in [('cases',int,None),('p1-input',int,1200),('p2-input',int,1600),('output-each',int,150),('usd-per-m-input',float,0.40),('usd-per-m-output',float,1.60),('idr-per-usd',float,18000),('reserve-factor',float,2)]:
    p.add_argument('--'+flag,type=kind,default=default,required=flag=='cases')
a=p.parse_args()
assert a.cases>0 and min(a.p1_input,a.p2_input,a.output_each,a.usd_per_m_input,a.usd_per_m_output,a.idr_per_usd,a.reserve_factor)>=0
usd=a.cases*((a.p1_input+a.p2_input)*a.usd_per_m_input+2*a.output_each*a.usd_per_m_output)/1_000_000
print(json.dumps({'cases':a.cases,'calls':a.cases*2,'assumptions':vars(a),'usd_estimate':round(usd,6),'idr_estimate':round(usd*a.idr_per_usd,2),'idr_with_reserve':round(usd*a.idr_per_usd*a.reserve_factor,2),'note':'Scenario only: excludes VPS, tax, fees, actual token variance, or retries beyond reserve.'},indent=2))
