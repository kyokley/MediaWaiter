/*global document: false */
/*global localStorage: false */
var seconds = 15;
var countdownTimer;
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
var binge_mode;
var has_next_link;
var should_redirect = true;
var aspectRatio = 9/16;

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
                    var finishedElement = document.getElementById('viewedText');
                    var toggleElement = document.getElementById('bingewatch-btn');
                    var rowElement = document.getElementById('binge-watch-row');

                    if(binge_mode && has_next_link && should_redirect){
                        finishedElement.innerHTML = "Marking file viewed... Binge mode active! Preparing next video <button class='btn btn-info play-controls' name='cancel-btn' id='cancel-btn' onclick='cancelBingeWatch();'><i class='bi-x-octagon-fill'></i> Cancel</button>";
                        if(toggleElement){
                            toggleElement.onclick = function(){};
                            toggleElement.setAttribute('disabled', 'disabled');
                            rowElement.style = "display:none;";
                        }
                    }else{
                        finishedElement.innerText = "Marking file viewed!";
                        rowElement.style = "display:none;";
                    }
                }
            });
    }
}

function cancelBingeWatch(){
    var finishedElement = document.getElementById('viewedText');
    var toggleElement = document.getElementById('bingewatch-btn');
    should_redirect = false;
    finishedElement.innerText = "Binge watching canceled";
    toggleElement.classList.remove('btn-success');
    toggleElement.classList.remove('btn-danger');
    toggleElement.innerText = "Disabled";
    toggleElement.classList.add('btn-danger');
    toggleElement.onclick = function(){};
    toggleElement.setAttribute('disabled', 'disabled');
}

function toggleBingeWatch(){
    var toggleElement = document.getElementById('bingewatch-btn');
    toggleElement.classList.remove('btn-success');
    toggleElement.classList.remove('btn-danger');

    if(should_redirect){
        should_redirect = false;
        toggleElement.innerText = "Disabled";
        toggleElement.classList.add('btn-danger');
    } else {
        should_redirect = true;
        toggleElement.innerText = "Enabled";
        toggleElement.classList.add('btn-success');
    }
}

function setupVideoPlayerPage(dirPath){
    video = document.getElementsByTagName('video')[0];
    player = video.parentElement.player;

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

    function toggleplay() {
        if(video.paused){
            video.play();
        } else {
            video.pause()
        }
    }

    function seekback() {
        var back = $('.skip-back')[0];
        back.click();
        player.userActive(true); // Display controls
    }

    function seekforward() {
        var forward = $('.skip-forward')[0];
        forward.click();
        player.userActive(true);
    }

    document.onkeydown = function(e) {
        // console.log(e.keyCode);
        if(e.keyCode == 32){
            toggleplay();
            return false;
        } else if(e.keyCode == 39){ // Right arrow
            seekforward();
            return false;
        } else if(e.keyCode == 37){ // Left arrow
            seekback();
            return false;
        }
    };
}

function hasScrolled(){
    var topNavbarHeight = $('#top-navbar').outerHeight() + 20;

    var st = $(this).scrollTop();
    var diff = Math.abs(lastScrollTop - st);
    if (diff <= delta)
        return;

    if(st > lastScrollTop && diff > topNavbarHeight){
        $('#top-navbar').removeClass('nav-show').addClass('nav-hide');
        $('#bottom-navbar').removeClass('nav-show').addClass('nav-hide');
        lastScrollTop = st;
    } else if(st < lastScrollTop && diff > topNavbarHeight){
            $('#top-navbar').removeClass('nav-hide').addClass('nav-show');
            $('#bottom-navbar').removeClass('nav-hide').addClass('nav-show');
        lastScrollTop = st;
    }

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

function resizeVideoJS(id){
    // Get the parent element's actual width
    const video = document.querySelector(id);
    var width = video.parentElement.offsetWidth;
    // Set width to fill parent element, Set height
    video.player.width(width);
    video.player.height(width * aspectRatio);
}

async function togglePictureInPicture() {
  // Close Picture-in-Picture window if any.
  if (documentPictureInPicture.window) {
    documentPictureInPicture.window.close();
    return;
  }

  // Open a Picture-in-Picture window.
  const video = document.querySelector("#video1");
  const width = video.parentElement.offsetWidth;
  const pipWindow = await documentPictureInPicture.requestWindow({
    width: width,
    height: width * aspectRatio,
  });

  // Copy all style sheets.
  [...document.styleSheets].forEach((styleSheet) => {
    try {
      const cssRules = [...styleSheet.cssRules].map((rule) => rule.cssText).join('');
      const style = document.createElement('style');

      style.textContent = cssRules;
      pipWindow.document.head.appendChild(style);
    } catch (e) {
      const link = document.createElement('link');

      link.rel = 'stylesheet';
      link.type = styleSheet.type;
      link.media = styleSheet.media;
      link.href = styleSheet.href;
      pipWindow.document.head.appendChild(link);
    }
  });

  // Move video to the Picture-in-Picture window and make it full page.
  pipWindow.document.body.append(video);
  video.classList.toggle("fullpage", true);

  // Listen for the PiP closing event to move the video back.
  pipWindow.addEventListener("pagehide", (event) => {
    const videoContainer = document.querySelector("#video-container");
    const pipVideo = event.target.querySelector("#video1");
    pipVideo.classList.toggle("fullpage", false);
    videoContainer.append(pipVideo);
  });

  pipWindow.onresize = function () {
      resizeVideoJS("#video1"); // Call the function on resize
  };
}
