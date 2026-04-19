import re

with open('/Users/roycel/Downloads/UCSD/VS Code Stuff/404 Fish Now Found/datahacks/frontend/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Locate the broken hidden-functional block
# It starts at <div class="hidden-functional"> and goes until <script type="module">>

broken_block_match = re.search(r'<div class="hidden-functional">.*?(<script type="module">>)', html, re.DOTALL)

if broken_block_match:
    correct_block = """    <div class="hidden-functional">
        <span id="top-temp"></span>
        <span id="top-turb"></span>
        <span id="top-dist"></span>
        <span id="sim-badge-top"></span>
        <div id="alert-badge"></div>
        <div id="clock"></div>
        <button id="voice-btn"></button>
        <audio id="alert-audio"></audio>
        <span id="lv-turb"></span>
        <span id="lv-dist"></span>
        <div id="temp-bar"></div>
        <div id="turb-bar"></div>
        <div id="status-pill"></div>
        <span id="sim-badge"></span>
        <div id="insight-text"></div>
        <div id="alert-panel"></div>
        <div id="alert-banner"></div>
        <div id="alert-text"></div>
        <svg><line id="thresh-line"></line><text id="thresh-label"></text></svg>
    </div>

<script type="module">"""
    html = html[:broken_block_match.start()] + correct_block + html[broken_block_match.end():]

with open('/Users/roycel/Downloads/UCSD/VS Code Stuff/404 Fish Now Found/datahacks/frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
