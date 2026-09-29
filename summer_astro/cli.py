import argparse
import json
from pathlib import Path
from .engine import SummerEngine
from .storage import ForecastStore
from .validation import evaluate, ablation

def main():
    parser=argparse.ArgumentParser(description="Summer Astro Engine v2")
    sub=parser.add_subparsers(dest="command",required=True)
    forecast=sub.add_parser("forecast");forecast.add_argument("request");forecast.add_argument("--output",required=True)
    forecast.add_argument("--db",default="./data/forecasts.sqlite")
    evaluation=sub.add_parser("evaluate");evaluation.add_argument("input");evaluation.add_argument("--output",required=True)
    abl=sub.add_parser("ablation");abl.add_argument("request");abl.add_argument("--output",required=True)
    args=parser.parse_args()
    if args.command=="forecast":
        value=SummerEngine(ForecastStore(args.db)).forecast(json.loads(Path(args.request).read_text()))
    elif args.command=="evaluate": value=evaluate(**json.loads(Path(args.input).read_text()))
    else: value=ablation(SummerEngine(),json.loads(Path(args.request).read_text()))
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False))
    print(json.dumps({"output":str(output),"status":value.get("status","completed")},ensure_ascii=False))

if __name__=="__main__": main()
