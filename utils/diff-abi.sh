#!/bin/bash

# This script is useful when updating ABIs as newer contracts are released.
vimdiff <(git show HEAD:pyflex/abi/$@ | jq '.') <(jq '.' < $@)
