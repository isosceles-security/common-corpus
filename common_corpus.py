#!/usr/bin/python3
# pip3 install warcio boto3

import sys
import os
import glob
import threading
import subprocess
import boto3
import warcio
import time
import json

### common-corpus configuration starts here

# AWS access key
ACCESS_KEY = ''
# AWS secret key
SECRET_KEY = ''
# command line for sancov enabled binary, with one %s where the testcase will be inserted
TARGET_CMDLINE = '/home/isosceles/source/pdfium/pdfium/Test/pdfium_test --ppm %s'
# sancov-enabled binary name
TARGET_BINARY = 'pdfium_test'
# file suffix to use for output
FILE_FORMAT = 'pdf'
# delete matching files after completion, empty string if no cleanup is required
CLEANUP_GLOB = '*.ppm'

### common-corpus configuration ends here

NTHREADS = 16

index = []
index_fd = -1

coverage = set()

corpus_id = 1
id_lock = threading.Lock()

tested_count = 0

exiting = False

def save_state():
    print("saving state")
    state = {   "index_offset": index_fd.tell(), 
                "corpus_id": corpus_id, 
                "tested_count": tested_count, 
                "coverage": list(coverage)
            }
    state_fd = open("state.dat", "w")
    json.dump(state, state_fd)

    return

def load_state(state_file):
    global corpus_id, tested_count, coverage
    print("loading state")
    state_fd = open(state_file, "r")
    state = json.load(state_fd)

    index_fd.seek(state["index_offset"])
    corpus_id = state["corpus_id"]
    tested_count = state["tested_count"]
    coverage = set(state["coverage"]) 

    return

def refill_index():
    try:
        for i in range(0, 4096):
            index.append([x.replace("\"", "") for x in index_fd.readline().rstrip().split(",")])
    except StopIteration:
        if len(index) == 0:
            return False

    return True

def common_corpus(thread_id):
    global corpus_id, exiting, tested_count

    s3 = boto3.Session().client('s3', aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY)

    test_file = "test%d.%s" % (thread_id, FILE_FORMAT)

    asan_env = os.environ.copy()
    asan_env["ASAN_OPTIONS"] = "coverage=1"

    while not exiting:
        try:
            item = index.pop()
        except IndexError:
            if not refill_index():
                print("\nthread %d finished" % thread_id)
                break

            continue

        if item[4] == "length":
            continue

        warc_path = item[1]

        try:
            warc_offset = int(item[2])
            warc_length = int(item[3])
        except ValueError:
            continue

        warc_range = 'bytes={}-{}'.format(warc_offset, warc_offset + warc_length - 1)

        sleep_sec = 1

        while True:
            try:
                obj = s3.get_object(Bucket="commoncrawl", Key=warc_path, Range=warc_range)
            except Exception:
                print("|%d-%d|" % (thread_id, sleep_sec), end='', flush=True)
                time.sleep(sleep_sec)

                if sleep_sec < 1024:
                    sleep_sec = sleep_sec * 2

                if exiting:
                    break

                continue

            break

        stream = obj['Body']

        record = next(warcio.ArchiveIterator(stream))

        try:
            file_data = record.content_stream().read()
        except Exception:
            print("error reading file data")
            exiting = True
            break

        fd = open(test_file, 'wb')

        fd.write(file_data)
        fd.close()

        cmd_line = TARGET_CMDLINE % test_file
        args = cmd_line.split()

        p = subprocess.Popen(args, env=asan_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.wait()

        sancov_file = "%s.%d.sancov" % (TARGET_BINARY, p.pid)

        if exiting:
            if os.path.isfile(sancov_file):
                os.remove(sancov_file)

            break

        try:
            fd = open(sancov_file, 'rb')
        except OSError:
            if not exiting:
                print("error: sancov file missing")
                exiting = True

            break

        sancov_data = fd.read()
        fd.close()

        if len(sancov_data) % 8 != 0: 
            print("error: malformed sancov file")
            sys.exit(-1)

        sancov_len = int(len(sancov_data) / 8)

        unique = False

        for i in range(1, sancov_len):
            edge = int.from_bytes(sancov_data[8*i:8*i+8], "little")

            if edge not in coverage:  
                coverage.add(edge)
                unique = True

        if unique:
            id_lock.acquire()
            unique_id = corpus_id
            corpus_id = corpus_id + 1
            id_lock.release()

            unique_path = "out/corpus%d.%s" % (unique_id, FILE_FORMAT)
            unique_sancov = "out/corpus%d.%s.sancov" % (unique_id, FILE_FORMAT)

            os.rename(test_file, unique_path)
            os.rename(sancov_file, unique_sancov)

            print("+", end='', flush=True)
        else:
            os.remove(sancov_file)
            print(".", end='', flush=True)

        tested_count = tested_count + 1

    if os.path.isfile(test_file):
        os.remove(test_file)

    for f in glob.glob(CLEANUP_GLOB):
        os.remove(f)

    return

def main():
    global index_fd, exiting

    if len(sys.argv) < 2:
        print("Usage: common_corpus.py <index_csv> [saved_state]")
        sys.exit(-1)

    if not os.path.exists("out"):
        os.mkdir("out")
    elif not os.path.isdir("out"):
        print("error: out is not a directory")
        sys.exit(-1)

    index_fd = open(sys.argv[1])

    _ = index_fd.readline()

    if len(sys.argv) == 3:
        load_state(sys.argv[2])

    if not refill_index():
        print("index csv is empty")   
        sys.exit(-1)

    threads = []

    for i in range(1, NTHREADS+1):
        t = threading.Thread(target=common_corpus, args=(i,))
        t.start()                      
        threads.append(t)

    for t in threads:
        try:
            t.join()
        except KeyboardInterrupt:
            print("exiting gracefully")
            exiting = True
            t.join()

    save_state()

if __name__ == '__main__':
    main()
