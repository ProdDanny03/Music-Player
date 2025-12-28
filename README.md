# Music Player

## Table Of Contents

- [Music Player](#music-player)
  - [Table Of Contents](#table-of-contents)
  - [About](#about)
  - [Features](#features)
  - [Installation](#installation)
  - [Usage](#usage)

## About

This is a simple music player for locally downloaded music files

## Features
| Features          | Description                                                           |
| :---------------- | :-------------------------------------------------------------------- |
| Auto Detect Music | Automatically finds music dynamically dynamically inside Music folder |
| Play/Stop/Pause   | Play/Stop/Pause your music                                            |
| Loop              | Loop list/song                                                        |
| Volume Bar        | Volume control                                                        |
| Progress Bar      | Change playback time position                                         |

## Installation

Download from releases section or build the binary yourself:
> *Microsoft Visual Studio MSVC and python3.13 is required to build*

```bash
git clone https://github.com/ProdDanny03/Music-Player.git

cd Music-Player

pip install -r requirements.txt

nuitka --msvc=latest --onefile --windows-console-mode=disable --windows-icon-from-ico=icon.ico --remove-output --output-filename="Music Player.exe" main.py
```

## Usage

Put songs into Music folder and the music player will auto detect them#