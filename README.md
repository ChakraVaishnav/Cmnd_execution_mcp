# How to run this in your local ??
Just clone the repo and run the below 2 cmnds 
pip install mcp psutil
python cmnd_execution_server.py

You don't have to run it all the time on your local claude will run it when ever it wants or when you mentioned you use a particular mcp server

# Config in Claude


"mcpServers": {

    "cmnd_execution_server": {
      "command": "YOUR_PYTHON_PATH",
      "args": [
      
        "PATH_IN_YOUR_LOCAL_OF_THAT_CLONED_CODE_FILE_LOCATION"
        
      ]
    }
  },
