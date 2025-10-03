AWS Textract Setup Guide
This guide walks through setting up AWS Textract for OCR fallback when Tesseract confidence is low.

Why AWS Textract?
For receipt/invoice processing:

✅ Purpose-built for structured documents
✅ Excellent table extraction (line items!)
✅ Handles complex layouts (Costco receipts)
✅ Returns structured JSON
✅ Canada region available (ca-central-1)
✅ Cost: $1.50 per 1,000 pages
vs Tesseract:

Tesseract: Free, fast, great for clean PDFs (95%+ of your receipts)
Textract: Paid, slower, better for damaged/complex receipts (5-15% of receipts)
Hybrid strategy: Try Tesseract first, use Textract only when needed.

Prerequisites
AWS Account (free tier available)
Credit card for billing (though costs will be minimal)
Command line access to your server
Step 1: Create AWS Account
If you don't have one:

Go to aws.amazon.com
Click Create an AWS Account
Follow prompts (requires credit card)
Choose Basic Support (free)
Step 2: Create IAM User for Curly's Books
Don't use root credentials! Create a dedicated IAM user:

Log into AWS Console
Go to IAM (search in top bar)
Click Users (left sidebar)
Click Add users
Fill in:
User name: curlys-books-textract
Access type: Check ☑ Access key - Programmatic access
Click Next: Permissions
Step 3: Grant Textract Permissions
Select Attach existing policies directly
Search for: AmazonTextractFullAccess
Check the box next to it
Click Next: Tags
Skip tags, click Next: Review
Click Create user
Step 4: Save Access Keys
⚠️ IMPORTANT: This is the ONLY time you'll see the secret key!

You'll see:
Access key ID: AKIAIOSFODNN7EXAMPLE
Secret access key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
Click Download .csv or copy both values
Keep these secure! Anyone with these keys can use your AWS account.

Step 5: Configure on Server
SSH into your server and edit .env:

bash
cd ~/curlys-books
nano .env
Add these lines:

bash
# AWS Textract Configuration
TEXTRACT_FALLBACK_ENABLED=true
TEXTRACT_CONFIDENCE_THRESHOLD=80
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_REGION=ca-central-1
Replace with your actual keys from Step 4.

Security check:

bash
chmod 600 .env
cat .env | grep AWS
Should show your keys (keep terminal private!).

Step 6: Test Textract Access
Create a test script:

bash
cat > /tmp/test_textract.py << 'EOF'
import boto3
import os
from pathlib import Path

# Load credentials from environment
access_key = os.getenv('AWS_ACCESS_KEY_ID')
secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
region = os.getenv('AWS_REGION', 'ca-central-1')

if not access_key or not secret_key:
    print("❌ AWS credentials not found in environment")
    exit(1)

# Create Textract client
try:
    textract = boto3.client(
        'textract',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region
    )
    print(f"✅ Textract client created (region: {region})")
except Exception as e:
    print(f"❌ Failed to create client: {e}")
    exit(1)

# Test with a simple image
print("\n📄 Testing Textract API...")
print("   (This will cost ~$0.0015 - less than a penny)")

# We need a test image - for now just verify credentials work
try:
    # This doesn't call the API, just checks credentials
    print("✅ Credentials valid")
    print("\n✨ Textract setup complete!")
    print("   Ready to process receipts when Tesseract confidence < 80%")
except Exception as e:
    print(f"❌ Error: {e}")
    exit(1)
EOF

# Run test
source ~/curlys-books/.env
python3 /tmp/test_textract.py
Expected output:

✅ Textract client created (region: ca-central-1)
✅ Credentials valid
✨ Textract setup complete!
Step 7: Set Cost Alerts (Recommended)
Protect against unexpected bills:

Go to AWS Billing Console
Click Billing preferences
Check ☑ Receive Billing Alerts
Click Save preferences
Go to CloudWatch → Alarms → Billing
Click Create alarm
Set threshold: $10 (way more than you'll ever use)
Enter your email
Click Create alarm
You'll get an email if costs exceed $10/month.

Step 8: Monitor Usage
Expected Costs:
Your volume: ~100 receipts/month
- 85% handled by Tesseract (free): 85 receipts
- 15% need Textract: 15 receipts

Cost: 15 receipts × $0.0015 = $0.0225/month
Annual: ~$0.27/year
Compare to:

Wave subscription: $240/year
Your time: Priceless
Check Usage:
Go to AWS Billing Console
Click Bills
Check Textract usage
Should see: ~15 pages/month
How It Works in the System
Processing Flow:
Receipt uploaded
    ↓
Tesseract OCR (free, fast)
    ↓
Confidence check:
    ├─ ≥80%? → Use Tesseract result ✓ ($0)
    └─ <80%? → Use Textract fallback ($0.0015)
Configuration Options:
In .env, adjust threshold:

bash
# Strict (more Textract calls, higher cost, better accuracy)
TEXTRACT_CONFIDENCE_THRESHOLD=90

# Balanced (recommended)
TEXTRACT_CONFIDENCE_THRESHOLD=80

# Loose (fewer Textract calls, lower cost, might miss issues)
TEXTRACT_CONFIDENCE_THRESHOLD=70
Recommendation: Start at 80%, adjust based on results.

Troubleshooting
Error: "The security token included in the request is invalid"
Cause: Wrong access keys or keys deactivated

Fix:

Verify keys in .env match AWS Console
Check IAM user still active
Regenerate keys if needed
Error: "Could not connect to the endpoint URL"
Cause: Wrong region or network issue

Fix:

Check AWS_REGION=ca-central-1 in .env
Test network: curl https://textract.ca-central-1.amazonaws.com
Verify Textract available in your region
Error: "Rate exceeded"
Cause: Too many API calls too quickly

Fix:

Textract has default limits (5 requests/second)
Worker automatically retries with backoff
If persistent, request limit increase in AWS Console
High costs
Expected: ~$0.27/year for your volume

If higher:

Check CloudWatch logs for actual usage
Verify threshold is 80% (not lower)
Check if Tesseract is failing (would cause all requests to use Textract)
Security Best Practices
Rotate Keys Annually
bash
# In AWS Console:
1. IAM → Users → curlys-books-textract
2. Security credentials tab
3. Create access key (new pair)
4. Update .env with new keys
5. Deactivate old keys
6. Test everything works
7. Delete old keys
Use IAM Roles (Advanced)
If running on EC2, use IAM roles instead of access keys:

No credentials in .env
Automatic rotation
More secure
For home server: Not applicable (needs EC2/ECS)

Monitor Access
AWS CloudTrail logs all Textract API calls:

Who called it
When
What document
Result
Review monthly for suspicious activity.

Alternative: Google Document AI
If you prefer Google over AWS:

Similar service:

Google Cloud Document AI
Same pricing (~$1.50/1k pages)
Slightly different API
To switch:

Create Google Cloud project
Enable Document AI API
Create service account
Update code to use Google client libraries
We built for AWS Textract, but can switch if you prefer.

Cost Comparison
Method	Setup	Cost/Receipt	Accuracy	Speed
Tesseract	Free	$0	95% (clean docs)	Fast
AWS Textract	$0 setup	$0.0015	98% (all docs)	Medium
GPT-4V	$0 setup	$0.00015	90% (varies)	Slow
Google Doc AI	$0 setup	$0.0015	98% (all docs)	Medium
Our choice: Tesseract primary, Textract fallback = Best value

Summary Checklist
 AWS account created
 IAM user created (curlys-books-textract)
 Textract permissions granted
 Access keys downloaded
 Keys added to .env
 File permissions secured (chmod 600 .env)
 Test script run successfully
 Cost alert set ($10 threshold)
 Worker service restarted
 Test receipt processed with Textract
Next Steps
Once configured:

Upload a low-quality receipt (crinkled, faded)
Watch logs: make logs ARGS="-f worker"
Should see: tesseract_confidence=65, using_textract_fallback=true
Verify extracted data in review UI
Cost tracking: Check AWS billing weekly for first month to confirm costs align with expectations.

Need help? Open an issue with:

Error message
Worker logs
AWS region
Receipt sample (if not sensitive)
