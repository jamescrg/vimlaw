/**
 * FullCalendar Integration for Events
 * Alpine.js component for calendar initialization and interaction
 */

// Reinitialize Alpine on HTMX swaps for the events container
document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target.id === "events" && typeof Alpine !== "undefined") {
    // Small delay to ensure DOM is ready
    setTimeout(() => {
      Alpine.initTree(event.detail.target);
    }, 10);
  }
});

// In calendar mode, intercept eventsChanged triggers and refetch instead of reloading
// Allow all other requests (view mode changes, filter changes, etc.) through
document.body.addEventListener("htmx:beforeRequest", (event) => {
  const target = event.detail.target;
  if (target && target.id === "events") {
    const calendarContainer = document.getElementById("fullcalendar-container");
    if (calendarContainer && calendarContainer._x_dataStack) {
      // We're in calendar mode - check what triggered this request
      const elt = event.detail.elt;
      const triggeringEvent = event.detail.triggeringEvent;

      // Only block if this is from the eventsChanged trigger (not eventsViewChanged)
      // The triggering event type tells us which custom event fired
      if (elt.id === "events" && triggeringEvent?.type === "eventsChanged") {
        const alpineData = calendarContainer._x_dataStack[0];
        if (alpineData && alpineData.calendar) {
          event.preventDefault();
          alpineData.calendar.refetchEvents();
        }
      }
    }
  }
});

document.addEventListener("alpine:init", () => {
  Alpine.data("eventsCalendar", () => ({
    calendar: null,

    initCalendar() {
      const calendarEl = this.$el;

      this.calendar = new FullCalendar.Calendar(calendarEl, {
        // Core settings
        initialView: "dayGridMonth",
        headerToolbar: {
          left: "prev,next today",
          center: "title",
          right: "dayGridMonth,timeGridWeek,timeGridDay",
        },

        // Event source - JSON API
        events: {
          url: "/events/api/",
          method: "GET",
          failure: function () {
            console.error("Failed to load events");
          },
        },

        // Drag and drop
        editable: true,
        eventStartEditable: true,
        eventDurationEditable: true,

        // Event handlers
        eventClick: (info) => this.handleEventClick(info),
        eventDrop: (info) => this.handleEventDrop(info),
        eventResize: (info) => this.handleEventResize(info),
        dateClick: (info) => this.handleDateClick(info),

        // Display settings
        nowIndicator: true,
        dayMaxEvents: true,
        navLinks: true,

        // Responsive
        height: "auto",

        // Custom button styling to match app
        themeSystem: "standard",
      });

      this.calendar.render();

      // Listen for filter changes to refresh calendar
      document.body.addEventListener("eventsChanged", () => {
        this.calendar.refetchEvents();
      });
    },

    handleEventClick(info) {
      // Prevent default behavior
      info.jsEvent.preventDefault();
      info.jsEvent.stopPropagation();

      // Open the edit modal using HTMX
      const eventId = info.event.id;
      htmx.ajax("GET", `/events/${eventId}/edit`, {
        target: "#htmx-modal-container",
        swap: "innerHTML",
      }).then(() => {
        window.dispatchEvent(new CustomEvent("open-modal"));
      });
    },

    handleEventDrop(info) {
      // Reschedule event via quick-update endpoint
      const event = info.event;
      const updateData = {
        date: this.formatDate(event.start),
      };

      if (!event.allDay && event.start) {
        updateData.start_time = this.formatTime(event.start);
        if (event.end) {
          updateData.end_time = this.formatTime(event.end);
        }
      } else {
        updateData.start_time = null;
        updateData.end_time = null;
      }

      this.quickUpdate(event.id, updateData, info);
    },

    handleEventResize(info) {
      // Update duration via quick-update endpoint
      const event = info.event;
      const updateData = {
        date: this.formatDate(event.start),
        start_time: this.formatTime(event.start),
        end_time: this.formatTime(event.end),
      };

      this.quickUpdate(event.id, updateData, info);
    },

    handleDateClick(info) {
      // Open add modal with pre-filled date
      htmx.ajax("GET", `/events/add?date=${info.dateStr}`, {
        target: "#htmx-modal-container",
        swap: "innerHTML",
      }).then(() => {
        window.dispatchEvent(new CustomEvent("open-modal"));
      });
    },

    formatDate(date) {
      // Format as YYYY-MM-DD
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, "0");
      const day = String(date.getDate()).padStart(2, "0");
      return `${year}-${month}-${day}`;
    },

    formatTime(date) {
      // Format as HH:MM:SS
      const hours = String(date.getHours()).padStart(2, "0");
      const minutes = String(date.getMinutes()).padStart(2, "0");
      const seconds = String(date.getSeconds()).padStart(2, "0");
      return `${hours}:${minutes}:${seconds}`;
    },

    quickUpdate(eventId, data, info) {
      // Get CSRF token from body attribute
      const csrfToken = this.getCsrfToken();

      fetch(`/events/${eventId}/quick-update`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify(data),
      })
        .then((response) => {
          if (!response.ok) {
            // Revert on failure
            info.revert();
            console.error("Failed to update event");
          }
        })
        .catch((error) => {
          info.revert();
          console.error("Error updating event:", error);
        });
    },

    getCsrfToken() {
      // Try to get from body hx-headers attribute
      const hxHeaders = document.body.getAttribute("hx-headers");
      if (hxHeaders) {
        try {
          const headers = JSON.parse(hxHeaders);
          if (headers["X-CSRFToken"]) {
            return headers["X-CSRFToken"];
          }
        } catch (e) {
          console.error("Failed to parse hx-headers", e);
        }
      }

      // Fallback to cookie
      const name = "csrftoken";
      const cookies = document.cookie.split(";");
      for (let cookie of cookies) {
        cookie = cookie.trim();
        if (cookie.startsWith(name + "=")) {
          return cookie.substring(name.length + 1);
        }
      }
      return "";
    },

    destroy() {
      if (this.calendar) {
        this.calendar.destroy();
      }
    },
  }));
});
