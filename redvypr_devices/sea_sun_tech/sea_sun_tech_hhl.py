import logging
import sys
import numpy as np
import time

# Setup logging module
# logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)


def pop_channel_sequence(decoded_data_all, channel_sequence):
    """
    Removes the first occurrence of the `channel_sequence` from `decoded_data_all`,
    returns the removed data, and modifies the original list.

    Args:
        decoded_data_all (list): List of data entries, e.g., [[channel, data], ...]
        channel_sequence (list): List of channel IDs to match, e.g., [0, 1, 2, 31]

    Returns:
        list: The removed data of the matched sequence, or `None` if the sequence is not found.
    """
    start_index = None

    # Find the starting index of the sequence
    for i in range(len(decoded_data_all) - len(channel_sequence) + 1):
        match = True
        for j, channel in enumerate(channel_sequence):
            if decoded_data_all[i + j][0] != channel:
                match = False
                break
        if match:
            start_index = i
            break

    # Remove the sequence and return the data
    if start_index is not None:
        end_index = start_index + len(channel_sequence)
        removed_data = decoded_data_all[start_index:end_index]
        del decoded_data_all[start_index:end_index]
        return removed_data
    else:
        return None


class HHL:
    """A processor for the HHL binary datastream from Sea & Sun Technology."""

    def __init__(self, verbosity=logging.DEBUG, config=None):
        if config is None:
            config = {}
        self.logger = logging.getLogger("redvypr_devices.sea_sun_tech_hhl.hhl")
        self.logger.setLevel(verbosity)
        self.config = config
        self.buffer = b""  # a binary buffer for the rawdata
        self.buffer_time = []
        self.ngood = 0
        self.nbad = 0

    def add_to_buffer(self, data, data_time=None):
        """
        Adds data to the internal buffer that is used to process the data
        Args:
            data:

        Returns:

        """
        self.buffer += data
        if data_time is None:
            data_time = [time.time()] * len(data)
        self.buffer_time.extend(data_time)


    def process_buffer(self):
        """
        Processes the data found in the buffer

        Returns:

        """
        funcname = __name__ + ".process_buffer():"
        nbad = 0

        decoded_data_tmp = self.decode_rawdata(hhldata=self.buffer, hhldata_time=self.buffer_time)
        decoded_data = decoded_data_tmp[0]
        self.buffer = decoded_data_tmp[1]
        self.buffer_time = decoded_data_tmp[2]
        #print("Buffer lengths",len(self.buffer),len(self.buffer_time))
        return decoded_data



    def inspect_rawdata(self, hhldata, minchannels=4, minsequence_repeat = 2):
        """
        Inspects a binary datastream for valid HHL format,
        returns a channel_sequence or None
        """
        funcname = __name__ + ".inspect_rawdata():"
        flag_found_channel0 = False
        flag_channel_sequence_done = False
        nmin = minsequence_repeat * (minchannels * 3 + 3)
        # check for a valid HHL packet first, if found loop over packets and seek for channel 0, if found check if buffer is still enough to create one datapacket
        # Seek for a start, find two "H" and one "L" pattern
        n = len(hhldata)
        print(funcname + "Processing length", n)
        if n >= nmin:  # We need at least 3*minchannels + numalign bytes for one complete datapacket
            # for i in range(3):
            data_check = hhldata
            last_channel = -1
            channel_sequence = []
            current_channel_sequence = []
            channels_found = []
            num_sequence_found = 0
            i = 0
            while(len(data_check))>3:
                data_tmp = self.decode_HHL(data_check)
                # Check if the datastream is valid, if not delete the first byte and try again
                if data_tmp is not None:
                    channel = data_tmp[0]
                    data = data_tmp[1]
                    print(f"Found valid HHL packet after:{i},{channel=},{data=}")
                    if flag_found_channel0 == False and channel != 0:
                        print("Found channel, skipping looking for channel 0 first")
                        data_check = data_check[3:]
                        continue
                    if flag_found_channel0 == False and channel == 0:
                        print("Found channel 0")
                        flag_found_channel0 = True

                    # Check if there is a channel with a larger number
                    if (channel > last_channel) and flag_channel_sequence_done == False:
                        channel_sequence.append(channel)
                    elif (channel < last_channel) and flag_channel_sequence_done == False:
                        print(f"Channel sequence done:{channel_sequence}")
                        flag_channel_sequence_done = True
                        #return channel_sequence

                    # Check for a sequence
                    if flag_channel_sequence_done:
                        if channel == 0:
                            print("Starting new sequence")
                            if len(current_channel_sequence) == len(channel_sequence):
                                print("Sequence done", current_channel_sequence)
                                num_sequence_found += 1
                                if num_sequence_found >= minsequence_repeat:
                                    print(f"Found {num_sequence_found} sequences")
                                    return channel_sequence

                            current_channel_sequence = [channel]
                        elif channel > last_channel:
                            current_channel_sequence.append(channel)



                    if (channel > last_channel) or (channel == 0):
                        print("Found channel",channel)
                        last_channel = channel
                        channels_found.append(channel)
                        data_check = data_check[3:]
                    else: # reset
                        print("Resetting")
                        channels_found = []
                        last_channel = -1
                        i += 1
                        data_check = data_check[1:]
                else:
                    # print('Did not found valid HHL packet')
                    i += 1
                    data_check = data_check[1:]
                    flag_found_channel0 = False
                    flag_channel_sequence_done = False

    def decode_rawdata(self, hhldata, hhldata_time=None):
        """
        Decodes rawdata with very simple plausibility checks
        - format need to be hhl
        - the current channel must be larger than the last one, or zero
        """
        funcname = __name__ + ".decode_rawdata():"
        # check for a valid HHL packet first, if found loop over packets and seek for channel 0, if found check if buffer is still enough to create one datapacket
        # Seek for a start, find two "H" and one "L" pattern
        nmin = 3
        n = len(hhldata)
        data_decoded = []
        #print(funcname + "Processing length", n)
        if hhldata_time:
            data_check_time = hhldata_time
        else:
            data_check_time = None

        if n >= nmin:  # We need at least 3*minchannels + numalign bytes for one complete datapacket
            # for i in range(3):
            data_check = hhldata
            if hhldata_time:
                data_check_time = hhldata_time
            last_channel = -1
            num_sequence_found = 0
            i = 0
            while (len(data_check)) >= 3:
                data_tmp = self.decode_HHL(data_check)
                if hhldata_time:
                    data_tmp_time = data_check_time[0] # Take the first element
                # Check if the datastream is valid, if not delete the first byte and try again
                if data_tmp is not None:
                    channel = data_tmp[0]
                    data_channel = data_tmp[1]
                    #print(f"Found valid HHL packet:byte offset:{i},{channel=},{data_channel=}")
                    if (channel > last_channel) or (channel == 0):
                        #print("Found channel", channel)
                        last_channel = channel
                        if hhldata_time:
                            data_decoded.append((channel, data_channel, data_tmp_time))
                        else:
                            data_decoded.append((channel, data_channel))

                        data_check = data_check[3:]
                        if hhldata_time:
                            data_check_time = data_check_time[3:]
                    else:  # reset
                        #print("Re-aligning")
                        channels_found = []
                        last_channel = -1
                        i += 1
                        data_check = data_check[1:]
                        if hhldata_time:
                            data_check_time = data_check_time[1:]
                else:
                    # print('Did not found valid HHL packet')
                    i += 1
                    data_check = data_check[1:]
                    if hhldata_time:
                        data_check_time = data_check_time[1:]

        return (data_decoded, data_check, data_check_time)

    def decode_HHL(self, hhldata):
        """
        Decodes a three bytes hhldata bytes array into channel, data
        Args:
            hhldata:

        Returns:

        """
        # Check if its a valid packet
        if len(hhldata) >= 2:
            # print('data',data,data[0:1])
            FLAG0 = hhldata[0] & 0x01 == 1
            FLAG1 = hhldata[1] & 0x01 == 1
            FLAG2 = hhldata[2] & 0x01 == 0
            if FLAG0 and FLAG1 and FLAG2:
                pass
            else:
                return None
        else:
            return None

        HHL0 = hhldata[0]
        HHL1 = hhldata[1]
        HHL2 = hhldata[2]
        # print("HHL: {:2x} {:2x} {:2x}".format(HHL0, HHL1, HHL2))
        channel = HHL2 >> 3
        data = HHL0 >> 1
        data = data | ((HHL1 & 0xFE) << 6)
        data = data | ((HHL2 & 0x06) << 13)
        return [channel, data]

    def valid_packet(self, data):
        """
        Checks if the datapacket is valid by testing of the first three bytes have the HHL pattern
        Args:
            data:

        Returns: bool

        """
        if len(data) >= 2:
            # print('data',data,data[0:1])
            FLAG0 = data[0] & 0x01 == 1
            FLAG1 = data[1] & 0x01 == 1
            FLAG2 = data[2] & 0x01 == 0
            if FLAG0 and FLAG1 and FLAG2:
                return True
            else:
                return False
        else:
            return False
