/*global document: false */
/*global localStorage: false */
var seconds = 15;
var countdownTimer;
var pretext = "This file will be downloaded automatically in <b>";
var cancelBtn;
var filePath;
var video;
var VIDEO_RESET_PERCENT = 0.98;
var viewedUrl;
var guid;
var viewed;

function cancelClick(srcElement){
    clearInterval(countdownTimer);
    var countdown = document.getElementById('countdown');
    if(countdown){
        countdown.innerHTML = "Download canceled";
        if(srcElement !== null){
            srcElement.setAttribute("disabled", "disabled");
        }
    }
}

function secondPassed() {
    var remainingSeconds = seconds;
    var text;
    if (remainingSeconds === 1){
        text = pretext + remainingSeconds + " </b>sec.";
    } else {
        text = pretext + remainingSeconds + " </b>secs.";
    }
    document.getElementById('countdown').innerHTML = text;

    if (seconds === 0) {
        document.getElementById('countdown').innerHTML = "Download started";
        document.getElementById("download").src=filePath;
        clearInterval(countdownTimer);
        countdownTimer = 0;
        if (cancelBtn){
            cancelBtn.removeEventListener("click", cancelClickEvent);
            cancelBtn.setAttribute("disabled", "disabled");
        }
    } else {
        seconds--;
    }
}

function setupAutoDownloadCountdown(){
    document.getElementById('countdown').innerHTML = pretext + seconds + " </b>secs.";
    countdownTimer = setInterval(secondPassed, 1000);
}

function prepareDataTable($){
    var tableElement = $('#myTable');

    tableElement.dataTable({
        stateSave: true,
        autoWidth: false,
        searching: false,
        paginate: false,
        ordering: false,
        info: false,
        responsive: {
            details: {
                type: 'column',
                target: -1
            }
        },
        columnDefs: [{
                    className: 'control',
                    orderable: false,
                    targets: -1
        }]
    });
}

function storeVideoPosition(filename, video){
    var offset = Math.max(video.currentTime - 30, 0);
    console.log("Storing position at " + offset);
    localStorage[filename] = offset;
}

function clearVideoPosition(filename){
    console.log("Clearing video position");
    localStorage.removeItem(filename);
}

function markViewed(guid){
    if(!viewed){
        viewed = true;
        jQuery.ajax({url: viewedUrl + guid,
                type: 'POST',
                dataType: 'json',
                data: {viewed: 'true',
                       guid: guid,
                       },
                success: function(json){
                    console.log(json);
                    var text = document.getElementById('viewedText');
                    text.innerText = "Marking file viewed!";
                }
                });
    }
}

function setVideoPosition(filename, video){
    var offset = localStorage.getItem(filename);
    if(offset !== null){
        video.currentTime = parseInt(offset);
    }
}

function setupVideoPlayerPage(filename){
    video = document.getElementsByTagName('video')[0];

    var timer = null;
    function tick() {
        if(video.duration > 10){
            if(video.currentTime / video.duration < VIDEO_RESET_PERCENT){
                storeVideoPosition(filename, video);
            } else {
                clearVideoPosition();
                markViewed(guid);
            }
        }
        video.removeEventListener('pause', onpause);
        start(); // Need to reset the timer
    }

    function start() {
        timer = setTimeout(tick, 15000);
        video.removeEventListener('play', start);
        video.addEventListener('pause', onpause);
    }

    function stop() {
        clearTimeout(timer);
    }

    function stopAndClearStorage(){
        stop();
        clearVideoPosition(filename);
    }

    function onpause() {
        stop();
        if(video.duration > 10){
            if(video.currentTime / video.duration < VIDEO_RESET_PERCENT){
                storeVideoPosition(filename, video);
            } else {
                clearVideoPosition(filename);
                markViewed(guid);
            }
        }
        video.addEventListener('play', start);
        video.removeEventListener('pause', onpause);
    }

    video.addEventListener('play', start);
    video.addEventListener('ended', stopAndClearStorage);
}
