import boto3
import pandas as pd
from datetime import datetime, timezone

# Configuration
EXCEL_FILE = 'servers.xlsx'  # Input Excel file
REGION = 'ap-southeast-2'         # Change this to match your AWS Region (e.g., 'ap-south-1')

ec2 = boto3.client('ec2', region_name=REGION)

def backup_servers_from_excel():
    # 1. Load the input Excel file
    try:
        df = pd.read_excel(EXCEL_FILE)
        print(f"Successfully loaded {len(df)} rows from {EXCEL_FILE}")
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return

    now_utc = datetime.now(timezone.utc)
    timestamp = now_utc.strftime('%Y-%m-%d-%H-%M')
    
    backup_results = []
    created_ami_ids = []

    # 2. Iterate through each row in the Excel sheet
    for index, row in df.iterrows():
        server_name = str(row.get('Server Name', f'Server-{index}'))
        ip_address = row.get('IP Address')

        if pd.isna(ip_address):
            print(f"[{index+1}] Skipping '{server_name}': Missing IP address.")
            backup_results.append({
                'Server Name': server_name,
                'IP Address': 'N/A',
                'Instance ID': 'N/A',
                'AMI ID': 'N/A',
                'AMI Name': 'N/A',
                'Final Status': 'Skipped - Missing IP',
                'Timestamp (UTC)': timestamp
            })
            continue

        ip_address = str(ip_address).strip()
        print(f"\n[{index+1}] Processing: {server_name} (IP: {ip_address})")

        try:
            # 3. Find the AWS EC2 Instance ID using Private IP
            response = ec2.describe_instances(
                Filters=[
                    {'Name': 'private-ip-address', 'Values': [ip_address]},
                    {'Name': 'instance-state-name', 'Values': ['running']}
                ]
            )

            instances = []
            for reservation in response['Reservations']:
                instances.extend(reservation['Instances'])

            # Fallback: check Public IP if private IP yielded no results
            if not instances:
                response = ec2.describe_instances(
                    Filters=[
                        {'Name': 'ip-address', 'Values': [ip_address]},
                        {'Name': 'instance-state-name', 'Values': ['running']}
                    ]
                )
                for reservation in response['Reservations']:
                    instances.extend(reservation['Instances'])

            if not instances:
                print(f" -> Warning: No running EC2 instance found matching IP {ip_address}")
                backup_results.append({
                    'Server Name': server_name,
                    'IP Address': ip_address,
                    'Instance ID': 'Not Found',
                    'AMI ID': 'N/A',
                    'AMI Name': 'N/A',
                    'Final Status': 'Failed - Instance Not Found',
                    'Timestamp (UTC)': timestamp
                })
                continue

            # 4. Create AMI for the matched instance(s)
            for instance in instances:
                instance_id = instance['InstanceId']
                
                safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '-' for c in server_name)
                ami_name = f"ExcelBackup-{safe_name}-{instance_id}-{timestamp}"
                
                print(f" -> Found Instance ID: {instance_id}. Initiating AMI backup...")
                
                image = ec2.create_image(
                    InstanceId=instance_id,
                    Name=ami_name,
                    Description=f"Automated backup from Excel list for {server_name} ({ip_address})",
                    NoReboot=True
                )
                
                ami_id = image['ImageId']
                created_ami_ids.append(ami_id)
                print(f" -> Initiated AMI ID: {ami_id}")

                backup_results.append({
                    'Server Name': server_name,
                    'IP Address': ip_address,
                    'Instance ID': instance_id,
                    'AMI ID': ami_id,
                    'AMI Name': ami_name,
                    'Final Status': 'Pending',
                    'Timestamp (UTC)': timestamp
                })

        except Exception as e:
            print(f" -> Error processing {server_name} ({ip_address}): {e}")
            backup_results.append({
                'Server Name': server_name,
                'IP Address': ip_address,
                'Instance ID': 'Error',
                'AMI ID': 'N/A',
                'AMI Name': 'N/A',
                'Final Status': f'Error: {str(e)}',
                'Timestamp (UTC)': timestamp
            })

    # 5. Wait for all initiated AMIs to finish building and become 'available'
    if created_ami_ids:
        print(f"\nWaiting for {len(created_ami_ids)} AMI(s) to finish creating in AWS...")
        print("This can take 5-30 minutes depending on disk size. Please keep this window open...")
        
        try:
            waiter = ec2.get_waiter('image_available')
            # Polls every 15 seconds, waits up to 2 hours (480 attempts)
            waiter.wait(
                ImageIds=created_ami_ids,
                WaiterConfig={'Delay': 15, 'MaxAttempts': 480}
            )
            print("ALL AMIs ARE NOW 100% AVAILABLE AND CONFIRMED!")
        except Exception as e:
            print(f"Warning while waiting for AMIs: {e}")

        # Re-check final exact status of each AMI from AWS
        final_images = ec2.describe_images(ImageIds=created_ami_ids)['Images']
        status_map = {img['ImageId']: img['State'].upper() for img in final_images}

        for item in backup_results:
            if item['AMI ID'] in status_map:
                item['Final Status'] = f"CONFIRMED ({status_map[item['AMI ID']]})"

    # 6. Save the confirmed report to Excel
    if backup_results:
        output_filename = f"Confirmed_Backup_Report_{timestamp}.xlsx"
        report_df = pd.DataFrame(backup_results)
        report_df.to_excel(output_filename, index=False)
        print(f"\n==========================================")
        print(f"Confirmed Report saved: {output_filename}")
        print(f"==========================================")

if __name__ == '__main__':
    backup_servers_from_excel()