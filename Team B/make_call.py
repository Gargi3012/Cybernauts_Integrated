import os
import argparse
import sys
from dotenv import load_dotenv

# Ensure root & Team B on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from Pillar_2.outbound_call import place_outbound_call

def place_test_call(to_number: str):
    load_dotenv()
    print(f"Initiating outbound test call to {to_number} via Plivo...")
    try:
        call_id = place_outbound_call(to_number)
        print(f"✅ Call placed successfully! Plivo Call UUID: {call_id}")
    except Exception as e:
        print(f"❌ Failed to place Plivo call: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Make an outbound call using Plivo")
    parser.add_argument("--to", required=True, help="The phone number to call (e.g. +917988207356)")
    args = parser.parse_args()
    
    place_test_call(args.to)
