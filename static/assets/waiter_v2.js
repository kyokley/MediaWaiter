/*global document: false */
/*global localStorage: false */
var seconds = 15;
var countdownTimer;
var pretext = "This file will be downloaded automatically in <b>";
var cancelBtn;
var filePath;
var video;
var VIDEO_RESET_PERCENT = 0.95;
var viewedUrl;
var offsetUrl;
var guid;
var viewed;
var didScroll;
var lastScrollTop = 0;
var delta = 10;
var navbarHeight = $('.navbar-fixed-top').outerHeight() + 20;
var binge_mode;
var has_next_link;
var should_redirect = true;

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
    var offset = Math.max(video.currentTime, 0);
    console.log("Attempting to store video position");
    jQuery.ajax({url: offsetUrl + guid + '/' + filename + '/',
                 type: 'POST',
                 data: {'offset': offset},
                 success: function(json){
                    console.log("Stored position at " + offset);
                 }
            });
}

function getVideoPosition(filename, guid, video){
    console.log("Attempting to get video position");
    if(localStorage.getItem(filename)){
        video.currentTime(localStorage.getItem(filename));
        localStorage.removeItem(filename);
    } else {
        jQuery.ajax({url: offsetUrl + guid + '/' + filename + '/',
                     type: 'GET',
                     dataType: 'json',
                     success: function(json, status, xhr){
                         console.log("Got video position: " + json.offset);
                         if(json.offset !== null){
                             video.currentTime(parseInt(json.offset));
                         }
                         video.play();
                     },
                     error: function(err){
                        console.log(err);
                    }
        });
    }
}

function clearVideoPosition(filename){
    console.log("Attempting to clear video position");
    jQuery.ajax({url: offsetUrl + guid + '/' + filename + '/',
                 type: 'DELETE',
                 dataType: 'json',
                 success: function(json){
                     console.log('Video position cleared');
                 },
                 error: function(err){
                    console.log(err);
                }
            });
}

function markViewed(guid){
    if(!viewed){
        viewed = true;
        jQuery.ajax({url: viewedUrl + guid + '/',
                type: 'POST',
                dataType: 'json',
                data: {viewed: 'true',
                       guid: guid},
                success: function(json){
                    console.log(json);
                    var finishedElement = document.getElementById('viewedText');
                    if(binge_mode && has_next_link){
                        finishedElement.innerHTML = "Marking file viewed... Binge mode active! Preparing next video <a class='btn btn-info play-controls' name='cancel-btn' id='cancel-btn' onclick='cancelBingeWatch();'><span class='glyphicon glyphicon-remove'></span> Cancel</a>";
                    }else{
                        finishedElement.innerText = "Marking file viewed!";
                    }
                }
            });
    }
}

function cancelBingeWatch(){
    var finishedElement = document.getElementById('viewedText');
    should_redirect = false;
    finishedElement.innerText = "Binge watching canceled";
}

function setupVideoPlayerPage(dirPath){
    video = document.getElementsByTagName('video')[0];

    var timer = null;
    function tick() {
        if(video.duration > 10){
            if(video.currentTime / video.duration < VIDEO_RESET_PERCENT){
                storeVideoPosition(dirPath, video);
            } else {
                clearVideoPosition(dirPath);
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
        clearVideoPosition(dirPath);
    }

    function onpause() {
        stop();
        if(video.duration > 10){
            if(video.currentTime / video.duration < VIDEO_RESET_PERCENT){
                storeVideoPosition(dirPath, video);
            } else {
                clearVideoPosition(dirPath);
                markViewed(guid);
            }
        }
        video.addEventListener('play', start);
        video.removeEventListener('pause', onpause);
    }

    video.addEventListener('play', start);
    video.addEventListener('ended', stopAndClearStorage);
}

function hasScrolled(){
    var st = $(this).scrollTop();
    if (Math.abs(lastScrollTop - st) <= delta)
        return;

    if(st > lastScrollTop && st > navbarHeight){
        $('.navbar-fixed-top').removeClass('nav-show').addClass('nav-hide');
        $('.navbar-fixed-bottom').removeClass('nav-show').addClass('nav-hide');
    } else {
        $('.navbar-fixed-top').removeClass('nav-hide').addClass('nav-show');
        $('.navbar-fixed-bottom').removeClass('nav-hide').addClass('nav-show');
    }

    lastScrollTop = st;
}

function scrollSetup(){
    $(window).scroll(function (event) {
        didScroll = true;
    });

    setInterval(function(){
            if(didScroll){
                hasScrolled();
                didScroll = false;
            }
        }, 250);
}
