#!/usr/bin/env python3

import oci
import sys
import argparse
from typing import List, Dict, Optional

class OCIVMAlarmManager:
    def __init__(self, compartment_id: Optional[str] = None, non_interactive: bool = False):
        """
        Initialize the OCI VM Alarm Manager

        Args:
            compartment_id: The OCID of the compartment containing the VMs (optional for single VM mode)
            non_interactive: If True, skip interactive prompts for automation
        """
        # Initialize OCI config - uses default profile from ~/.oci/config
        self.config = oci.config.from_file()

        # Initialize OCI clients
        self.compute_client = oci.core.ComputeClient(self.config)
        self.monitoring_client = oci.monitoring.MonitoringClient(self.config)
        self.notification_client = oci.ons.NotificationDataPlaneClient(self.config)
        self.notification_control_client = oci.ons.NotificationControlPlaneClient(self.config)

        self.compartment_id = compartment_id
        self.non_interactive = non_interactive

    def get_notification_topics(self) -> List[Dict]:
        """
        Get all notification topics in the compartment

        Returns:
            List of notification topics with their details
        """
        if not self.compartment_id:
            print("Error: Compartment ID required to list notification topics")
            return []

        print(f"Fetching notification topics in compartment: {self.compartment_id}")

        try:
            topics = self.notification_control_client.list_topics(
                compartment_id=self.compartment_id
            ).data

            topic_list = []
            for topic in topics:
                topic_info = {
                    'id': topic.topic_id,
                    'name': topic.name,
                    'description': topic.description,
                    'lifecycle_state': topic.lifecycle_state
                }
                topic_list.append(topic_info)
                print(f"Found topic: {topic.name} (ID: {topic.topic_id})")

            return topic_list

        except Exception as e:
            print(f"Error fetching notification topics: {str(e)}")
            return []

    def validate_notification_topic(self, topic_ocid: str) -> bool:
        """
        Validate that the notification topic exists and is accessible

        Args:
            topic_ocid: The OCID of the notification topic to validate

        Returns:
            True if topic is valid and accessible, False otherwise
        """
        try:
            topic = self.notification_control_client.get_topic(topic_id=topic_ocid)
            if topic.data.lifecycle_state == 'ACTIVE':
                print(f"✓ Notification topic validated: {topic.data.name}")
                return True
            else:
                print(f"✗ Notification topic is not active (state: {topic.data.lifecycle_state})")
                return False
        except Exception as e:
            print(f"✗ Error validating notification topic: {str(e)}")
            return False

    def get_vm_by_ocid(self, vm_ocid: str) -> Dict:
        """
        Get a specific VM instance by OCID

        Args:
            vm_ocid: The OCID of the VM instance

        Returns:
            VM instance details or None if not found
        """
        print(f"Fetching VM: {vm_ocid}")

        try:
            instance = self.compute_client.get_instance(instance_id=vm_ocid).data

            vm_info = {
                'id': instance.id,
                'display_name': instance.display_name,
                'lifecycle_state': instance.lifecycle_state,
                'availability_domain': instance.availability_domain
            }
            print(f"Found VM: {instance.display_name} (State: {instance.lifecycle_state})")
            return vm_info

        except Exception as e:
            print(f"Error fetching VM {vm_ocid}: {str(e)}")
            return None

    def get_all_vms(self) -> List[Dict]:
        """
        Get all VM instances in the specified compartment

        Returns:
            List of VM instances with their details
        """
        print(f"Fetching all VMs in compartment: {self.compartment_id}")

        try:
            instances = self.compute_client.list_instances(
                compartment_id=self.compartment_id,
                lifecycle_state="RUNNING"  # Only get running instances
            ).data

            vm_list = []
            for instance in instances:
                vm_info = {
                    'id': instance.id,
                    'display_name': instance.display_name,
                    'lifecycle_state': instance.lifecycle_state,
                    'availability_domain': instance.availability_domain
                }
                vm_list.append(vm_info)
                print(f"Found VM: {instance.display_name} (ID: {instance.id})")

            return vm_list

        except Exception as e:
            print(f"Error fetching VMs: {str(e)}")
            return []

    def create_alarm_for_vm(self, vm_name: str, notification_topic_ocid: str) -> bool:
        """
        Create an alarm for a specific VM using the provided query pattern

        Args:
            vm_name: The display name of the VM
            notification_topic_ocid: OCID of the notification topic for email alerts (required)

        Returns:
            True if alarm created successfully, False otherwise
        """
        alarm_name = f"{vm_name} - Unresponsive or Stopped Alert"

        # Query pattern from the user's example, adapted for the specific VM
        query = f'InstanceAccessibilityStatus[5m]{{resourceDisplayName = "{vm_name}"}}.mean() > 0 || InstanceAccessibilityStatus[5m]{{resourceDisplayName = "{vm_name}"}}.absent(10m) == 1'

        # Set up destinations for notifications (required)
        destinations = [notification_topic_ocid]

        alarm_details = oci.monitoring.models.CreateAlarmDetails(
            display_name=alarm_name,
            compartment_id=self.compartment_id,
            metric_compartment_id=self.compartment_id,
            namespace="oci_compute_instance_health",  # Correct namespace for InstanceAccessibilityStatus
            query=query,
            severity="CRITICAL",
            destinations=destinations,
            is_enabled=True,
            body=f"VM {vm_name} is unresponsive or in a stopped state. Please check the instance status.",
            pending_duration="PT5M",  # 5 minutes
            message_format="ONS_OPTIMIZED"  # Use proper OCI notification format
        )

        try:
            print(f"Creating alarm for VM: {vm_name}")
            response = self.monitoring_client.create_alarm(alarm_details)
            print(f"✓ Alarm created successfully for {vm_name} (Alarm ID: {response.data.id})")
            return True

        except Exception as e:
            print(f"✗ Error creating alarm for {vm_name}: {str(e)}")
            return False

    def create_alarms_for_all_vms_with_topic(self, notification_topic_ocid: str) -> Dict[str, bool]:
        """
        Create alarms for all VMs in the compartment using a specific notification topic

        Args:
            notification_topic_ocid: The OCID of the notification topic to use

        Returns:
            Dictionary with VM names as keys and success status as values
        """
        print(f"Using notification topic: {notification_topic_ocid}")

        vms = self.get_all_vms()

        if not vms:
            print("No VMs found in the compartment")
            return {}

        print(f"\nCreating alarms for {len(vms)} VMs...")
        results = {}

        for vm in vms:
            vm_name = vm['display_name']
            success = self.create_alarm_for_vm(vm_name, notification_topic_ocid)
            results[vm_name] = success

        return results

    def create_alarm_for_single_vm(self, vm_ocid: str, notification_topic_ocid: str) -> bool:
        """
        Create an alarm for a single VM specified by OCID

        Args:
            vm_ocid: The OCID of the VM instance
            notification_topic_ocid: OCID of the notification topic for email alerts

        Returns:
            True if alarm created successfully, False otherwise
        """
        # Get VM details first
        vm = self.get_vm_by_ocid(vm_ocid)

        if not vm:
            print(f"✗ VM not found or inaccessible: {vm_ocid}")
            return False

        if vm['lifecycle_state'] != 'RUNNING':
            print(f"⚠ Warning: VM {vm['display_name']} is not in RUNNING state (current: {vm['lifecycle_state']})")
            if not self.non_interactive:
                proceed = input("Do you want to create an alarm anyway? (y/n): ").lower().strip()
                if proceed != 'y':
                    print("Skipping alarm creation for non-running VM")
                    return False

        print(f"Creating alarm for VM: {vm['display_name']}")
        success = self.create_alarm_for_vm(vm['display_name'], notification_topic_ocid)

        if success:
            print(f"✓ Successfully created alarm for {vm['display_name']}")
        else:
            print(f"✗ Failed to create alarm for {vm['display_name']}")

        return success


    def print_summary(self, results: Dict[str, bool]):
        """Print a summary of the alarm creation process"""
        total = len(results)
        successful = sum(1 for success in results.values() if success)
        failed = total - successful

        print(f"\n{'='*50}")
        print(f"ALARM CREATION SUMMARY")
        print(f"{'='*50}")
        print(f"Total VMs processed: {total}")
        print(f"Alarms created successfully: {successful}")
        print(f"Failed alarm creations: {failed}")

        if failed > 0:
            print(f"\nFailed VMs:")
            for vm_name, success in results.items():
                if not success:
                    print(f"  - {vm_name}")

def get_vm_compartment_from_ocid(vm_ocid: str) -> str:
    """Extract compartment OCID from VM instance OCID if needed"""
    try:
        config = oci.config.from_file()
        compute_client = oci.core.ComputeClient(config)
        instance = compute_client.get_instance(instance_id=vm_ocid).data
        return instance.compartment_id
    except Exception as e:
        print(f"Error getting VM compartment: {str(e)}")
        return None

def main():
    """Main function to run the alarm creation process"""
    parser = argparse.ArgumentParser(
        description='Create OCI VM monitoring alarms',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Create alarms for all VMs in a compartment
  python oci_vm_alarms.py --compartment ocid1.compartment.oc1..abc123 --topic ocid1.onstopic.oc1..def456

  # Create alarm for one specific VM (compartment auto-detected)
  python oci_vm_alarms.py --vm-ocid ocid1.instance.oc1.iad.anuwcljruox3l7icuhsical76jiwbtnud37ckglq6po3d3rwl5gtoutlsbga --topic ocid1.onstopic.oc1..def456

  # Non-interactive mode for automation
  python oci_vm_alarms.py --vm-ocid ocid1.instance.oc1..ghi789 --topic ocid1.onstopic.oc1..def456 --non-interactive
        '''
    )

    parser.add_argument('--compartment', '--compartment-ocid',
                        help='OCID of the compartment containing VMs (required for all-VMs mode)')

    parser.add_argument('--topic', '--notification-topic', required=True,
                        help='OCID of the notification topic for email alerts (required)')

    parser.add_argument('--vm-ocid', '--vm-instance-ocid',
                        help='OCID of specific VM instance to monitor (single VM mode)')

    parser.add_argument('--non-interactive', action='store_true',
                        help='Skip interactive prompts for automation/scripting')

    args = parser.parse_args()

    # Determine mode and validate requirements
    single_vm_mode = bool(args.vm_ocid)

    if single_vm_mode:
        # Single VM mode - compartment is optional (will be auto-detected)
        vm_instance_ocid = args.vm_ocid
        compartment_id = args.compartment

        if not vm_instance_ocid.startswith('ocid1.instance.'):
            print("Error: Invalid VM instance OCID format. Must start with 'ocid1.instance.'")
            sys.exit(1)

        # Auto-detect compartment if not provided
        if not compartment_id:
            print("Auto-detecting compartment from VM instance...")
            compartment_id = get_vm_compartment_from_ocid(vm_instance_ocid)
            if not compartment_id:
                print("Error: Could not determine compartment from VM OCID. Please specify --compartment")
                sys.exit(1)
            print(f"Detected compartment: {compartment_id}")

    else:
        # All VMs mode - compartment is required
        if not args.compartment:
            print("Error: --compartment is required when not using --vm-ocid")
            parser.print_help()
            sys.exit(1)
        compartment_id = args.compartment
        vm_instance_ocid = None

    # Validate OCIDs
    if not compartment_id.startswith('ocid1.compartment.'):
        print("Error: Invalid compartment OCID format. Must start with 'ocid1.compartment.'")
        sys.exit(1)

    if not args.topic.startswith('ocid1.onstopic.'):
        print("Error: Invalid notification topic OCID format. Must start with 'ocid1.onstopic.'")
        sys.exit(1)

    try:
        # Initialize the alarm manager
        alarm_manager = OCIVMAlarmManager(compartment_id, args.non_interactive)

        # Validate the notification topic first
        if not alarm_manager.validate_notification_topic(args.topic):
            print("Error: Unable to validate notification topic. Please check the OCID and try again.")
            sys.exit(1)

        if single_vm_mode:
            # Create alarm for single VM
            print(f"Creating alarm for single VM: {vm_instance_ocid}")
            success = alarm_manager.create_alarm_for_single_vm(vm_instance_ocid, args.topic)

            if success:
                print(f"\n✓ Successfully created alarm for VM")
            else:
                print(f"\n✗ Failed to create alarm for VM")
                sys.exit(1)
        else:
            # Create alarms for all VMs using the provided topic
            results = alarm_manager.create_alarms_for_all_vms_with_topic(args.topic)

            # Print summary
            alarm_manager.print_summary(results)

    except oci.exceptions.ConfigFileNotFound:
        print("Error: OCI config file not found. Please run 'oci setup config' first.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()