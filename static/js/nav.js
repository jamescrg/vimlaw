
function getPage() {

    var path = window.location.pathname;

    var pathArray = path.split('/');

    var page = pathArray[1]

    if (page == '') {
        page = 'agenda';
    }

    return page;
}


function highlightNavLink() {

    var mainNav = document.querySelector('#nav-main');
    var navLinks = mainNav.querySelectorAll('.nav-link');

    for (link of navLinks) {

        if (link.id == 'nav-'+getPage()) {

            link.classList.add('active');

        }

    }

}

function checkDev() {

    path = window.location.hostname;
    var pathArray = path.split('.');
    dev = pathArray['0'];
    if (dev == 'dev') {
        var devItem = document.querySelector('.dev-flag');
        devItem.style.display = "inline";
    }

}

highlightNavLink();
